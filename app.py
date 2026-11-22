"""CareSlot clinic coordination demo (Flask + SQLite)."""
from datetime import date, datetime, timedelta
import re
import sqlite3

from flask import Flask, jsonify, render_template, request
from db import connection, init_db

app = Flask(__name__)
SLOT_TIMES = ("09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00")


def json_body():
    return request.get_json(silent=True) or {}


def find_doctor(text):
    lower = text.casefold()
    with connection() as conn:
        doctors = conn.execute("SELECT doctor_id,name FROM doctors WHERE available=1").fetchall()
    for doctor in doctors:
        surname = doctor["name"].split()[-1].casefold()
        if doctor["name"].casefold() in lower or re.search(rf"\b{re.escape(surname)}\b", lower):
            return dict(doctor)
    return None


def doctor_choice_prompt(text):
    lower = text.casefold()
    aliases = {
        "General Medicine": ("general", "family doctor", "gp"),
        "Dermatology": ("dermat", "skin doctor", "skin specialist"),
        "Cardiology": ("cardio", "heart doctor", "heart specialist"),
    }
    with connection() as conn:
        rows = conn.execute("SELECT name,specialty FROM doctors WHERE available=1 ORDER BY specialty,name").fetchall()
    for specialty, terms in aliases.items():
        if any(term in lower for term in terms):
            names = [row["name"] for row in rows if row["specialty"] == specialty]
            return f"I found {specialty}. Which doctor would you prefer: {', '.join(names)}?"
    groups = {}
    for row in rows:
        groups.setdefault(row["specialty"], []).append(row["name"])
    return "Which doctor would you prefer? " + "; ".join(
        f"{department}: {', '.join(names)}" for department, names in groups.items()
    ) + "."


def requested_date(text):
    lower = text.casefold()
    today = date.today()
    iso_date = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", lower)
    if iso_date:
        try:
            return date.fromisoformat(iso_date[1])
        except ValueError:
            pass
    if "day after tomorrow" in lower:
        return today + timedelta(days=2)
    if "tomorrow" in lower:
        return today + timedelta(days=1)
    if "today" in lower:
        return today
    weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6}
    for name, weekday in weekdays.items():
        if re.search(rf"\b(?:next\s+)?{name}\b", lower):
            days_ahead = (weekday - today.weekday()) % 7
            if days_ahead == 0 or re.search(rf"\bnext\s+{name}\b", lower):
                days_ahead += 7
            return today + timedelta(days=days_ahead)
    return today


def has_explicit_date(text):
    lower = text.casefold()
    return bool(re.search(r"\b(?:today|tomorrow|day after tomorrow|next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\b20\d{2}-\d{2}-\d{2}\b", lower)) or "today" in lower or "tomorrow" in lower


def parse_time(text):
    text = re.sub(r"\b([ap])\s*\.?\s*m\.?\b", r"\1m", text.casefold())
    text = re.sub(r"\b(noon|midday)\b", "12 pm", text)
    text = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b", lambda m: str({"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}[m[1]]), text)
    match = re.search(r"\b(9|10|11|12|1|2|3|4)(?::([0-5]\d))?\s*(am|pm)\b", text)
    if match:
        hour, minute, period = int(match[1]), int(match[2] or 0), match[3]
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    match = re.search(r"\b(?:at|around|about)\s+(9|10|11|12|1|2|3|4)(?::([0-5]\d))?\b", text)
    if match:
        hour, minute = int(match[1]), int(match[2] or 0)
        if hour in (1, 2, 3, 4):
            hour += 12
        return f"{hour:02d}:{minute:02d}"
    match = re.search(r"\b(09|10|11|12|14|15|16):([0-5]\d)\b", text)
    if match:
        return f"{match[1]}:{match[2]}"
    # Accept shorthand such as "make it 16" as 4 PM when the caller
    # already has the selected clinic slot in context.
    match = re.search(r"\b(?:at|on|make it|make)\s*(14|15|16)\b", text)
    return f"{match[1]}:00" if match else None


def display_time(value):
    """Render internal HH:MM values as clear 12-hour times."""
    if not value:
        return None
    return datetime.strptime(value, "%H:%M").strftime("%I:%M %p").lstrip("0")


def conversation_context(doctor, day):
    return {"doctor": doctor["name"], "date": day.isoformat()} if doctor else None


def available_slots(doctor_id, day, exclude_id=None):
    sql = "SELECT appointment_time FROM appointments WHERE doctor_id=? AND appointment_date=? AND status='booked'"
    params = [doctor_id, day.isoformat() if isinstance(day, date) else day]
    if exclude_id is not None:
        sql += " AND appointment_id<>?"
        params.append(exclude_id)
    with connection() as conn:
        booked = {row[0] for row in conn.execute(sql, params)}
    return [slot for slot in SLOT_TIMES if slot not in booked]


def get_or_create_patient(conn, name):
    name = " ".join(name.split())
    if not name or len(name) > 100:
        raise ValueError("Please provide a valid patient name (up to 100 characters).")
    conn.execute("INSERT OR IGNORE INTO patients(name) VALUES(?)", (name,))
    return conn.execute("SELECT patient_id FROM patients WHERE name=? COLLATE NOCASE", (name,)).fetchone()[0]


def risk_score(attended_before, lead_days):
    score, reasons = 20, []
    if not attended_before:
        score += 45
        reasons.append("previous missed appointment")
    if lead_days >= 7:
        score += 20
        reasons.append("booked 7 or more days in advance")
    elif lead_days >= 4:
        score += 10
        reasons.append("booked several days in advance")
    return min(score, 95), ", ".join(reasons) if reasons else "no major demo risk factors"


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/dashboard")
def dashboard():
    with connection() as conn:
        rows = conn.execute("""SELECT a.appointment_id AS id,a.appointment_date AS appt_date,
            a.appointment_time AS appt_time,a.status,p.name AS patient,d.name AS doctor,d.specialty
            FROM appointments a JOIN patients p USING(patient_id) JOIN doctors d USING(doctor_id)
            ORDER BY a.appointment_date,a.appointment_time""").fetchall()
        waiting = conn.execute("SELECT COUNT(*) FROM waitlist WHERE status='waiting'").fetchone()[0]
    appointments = [dict(row) for row in rows]
    for appointment in appointments:
        appointment["appt_time"] = display_time(appointment["appt_time"])
    today = date.today().isoformat()
    return jsonify(appointments=appointments,
                   total=sum(a["appt_date"] >= today and a["status"] == "booked" for a in appointments),
                   booked=sum(a["status"] == "booked" for a in appointments),
                   cancelled=sum(a["status"] == "cancelled" for a in appointments), waitlist=waiting)


@app.get("/api/doctors")
def doctors_directory():
    with connection() as conn:
        rows = conn.execute("SELECT doctor_id,name,specialty FROM doctors WHERE available=1 ORDER BY specialty,name").fetchall()
    return jsonify(doctors=[dict(row) for row in rows])


@app.get("/api/waitlist")
def get_waitlist():
    with connection() as conn:
        rows = conn.execute("""SELECT w.waitlist_id,p.name AS patient,d.name AS doctor,
            CASE WHEN w.status IN ('offered','accepted') THEN COALESCE(w.offered_date,w.preferred_date) ELSE w.preferred_date END AS preferred_date,
            CASE WHEN w.status IN ('offered','accepted') THEN COALESCE(w.offered_time,w.preferred_time) ELSE w.preferred_time END AS preferred_time,
            w.status FROM waitlist w
            JOIN patients p USING(patient_id) JOIN doctors d USING(doctor_id)
            ORDER BY w.created_at DESC,w.waitlist_id DESC""").fetchall()
    entries = [dict(row) for row in rows]
    for entry in entries:
        entry["preferred_time"] = display_time(entry["preferred_time"])
    return jsonify(waitlist=entries)


@app.post("/api/waitlist/<int:wid>/approve")
def approve_waitlist(wid):
    try:
        with connection() as conn:
            item = conn.execute("SELECT * FROM waitlist WHERE waitlist_id=? AND status='offered'", (wid,)).fetchone()
            if not item:
                return jsonify(message="No active offered waitlist entry found."), 404
            day = item["offered_date"] or item["preferred_date"]
            slot = item["offered_time"] or item["preferred_time"]
            if not day or not slot:
                return jsonify(message="The offered appointment date or time is missing."), 400
            conn.execute("INSERT INTO appointments(patient_id,doctor_id,appointment_date,appointment_time,booking_lead_days) VALUES(?,?,?,?,?)",
                         (item["patient_id"], item["doctor_id"], day, slot, max(0, (date.fromisoformat(day)-date.today()).days)))
            appointment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("UPDATE waitlist SET status='accepted' WHERE waitlist_id=?", (wid,))
        return jsonify(message=f"Appointment approved successfully! New appointment ID: #{appointment_id}.")
    except sqlite3.IntegrityError:
        return jsonify(message="This appointment slot has just been booked. Please choose another time."), 409


@app.post("/api/waitlist/<int:wid>/reject")
def reject_waitlist(wid):
    with connection() as conn:
        cur = conn.execute("UPDATE waitlist SET status='waiting',offered_date=NULL,offered_time=NULL WHERE waitlist_id=? AND status='offered'", (wid,))
        if not cur.rowcount:
            return jsonify(message="No active offered waitlist entry found."), 404
    return jsonify(message="Offer rejected. Patient returned to the waiting list.")


@app.post("/api/chat")
def chat():
    message = json_body().get("message", "")
    if not isinstance(message, str) or not message.strip():
        return jsonify(reply="Please enter a request."), 400
    message = message.strip()
    if len(message) > 500:
        return jsonify(reply="Please keep requests under 500 characters."), 400
    lower, day, doctor = message.casefold(), requested_date(message), find_doctor(message)

    if re.fullmatch(r"(?:hi|hello|hey|good\s+morning|good\s+afternoon|good\s+evening|good\s+day)[!. ,]*", lower):
        return jsonify(reply="Hello! I can help you find a doctor, check appointment times, or book a visit. What would you like to do?")

    asks_availability = any(word in lower for word in ("available", "availability", "free slot", "slots")) or (
        "free" in lower and ("doctor" in lower or doctor is not None)
    )
    if asks_availability:
        if not doctor:
            return jsonify(reply=doctor_choice_prompt(message))
        slots = available_slots(doctor["doctor_id"], day)
        shown_slots = ", ".join(display_time(slot) for slot in slots)
        return jsonify(reply=f"{doctor['name']} has these available slots on {day}: {shown_slots if slots else 'No slots available'}.", action="availability", context=conversation_context(doctor, day))

    if "waitlist" in lower or "waiting list" in lower:
        if not doctor:
            return jsonify(reply="Which doctor's waitlist? Choose a doctor from the clinic directory below.")
        match = re.search(r"(?:name is|i am|i'm)\s+([A-Za-z]+(?:\s+[A-Za-z]+)*?)(?=\s+(?:for|tomorrow|today|at)\b|[.,!?]*$)", message, re.I)
        if not match:
            match = re.search(r"\b(?:add|put|place)\s+(?!me\b|myself\b)([A-Za-z]+(?:\s+[A-Za-z]+)*?)\s+(?:to|on)\s+(?=dr\.?\s)", message, re.I)
        if not match:
            return jsonify(reply="Who should I add? For example: ‘Join Dr. Kumar’s waitlist. My name is Rahul Sharma.’ You can also include a day and time.")
        name, slot = match[1].strip(), parse_time(message)
        preferred_date = day.isoformat() if has_explicit_date(message) else None
        with connection() as conn:
            pid = get_or_create_patient(conn, name)
            conn.execute("INSERT INTO waitlist(patient_id,doctor_id,preferred_date,preferred_time) VALUES(?,?,?,?)", (pid, doctor["doctor_id"], preferred_date, slot))
        when = f"for {preferred_date}" if preferred_date else "for any day"
        when += f" at {display_time(slot)}" if slot else ""
        return jsonify(reply=f"{name} has been added to {doctor['name']}'s waitlist {when}. If a matching slot opens, it will appear here for staff approval.", action="waitlist")

    if "cancel" in lower:
        match = re.search(r"(?:appointment\s*)?#?\s*(\d+)", lower)
        if not match:
            return jsonify(reply="Please include an appointment ID, for example: cancel appointment 2.")
        aid = int(match[1])
        with connection() as conn:
            appointment = conn.execute("SELECT * FROM appointments WHERE appointment_id=? AND status='booked'", (aid,)).fetchone()
            if not appointment:
                return jsonify(reply=f"No active appointment #{aid} found.")
            doctor_name = conn.execute("SELECT name FROM doctors WHERE doctor_id=?", (appointment["doctor_id"],)).fetchone()[0]
            conn.execute("UPDATE appointments SET status='cancelled' WHERE appointment_id=?", (aid,))
            waiting = conn.execute("""SELECT waitlist_id,patient_id FROM waitlist WHERE doctor_id=?
                AND (preferred_date IS NULL OR preferred_date=?) AND status='waiting'
                AND (preferred_time IS NULL OR preferred_time=?)
                ORDER BY CASE WHEN preferred_time=? THEN 0 ELSE 1 END,created_at,waitlist_id LIMIT 1""",
                (appointment["doctor_id"], appointment["appointment_date"], appointment["appointment_time"], appointment["appointment_time"])).fetchone()
            patient_name = None
            if waiting:
                conn.execute("UPDATE waitlist SET status='offered',offered_date=?,offered_time=? WHERE waitlist_id=?", (appointment["appointment_date"], appointment["appointment_time"], waiting["waitlist_id"]))
                patient_name = conn.execute("SELECT name FROM patients WHERE patient_id=?", (waiting["patient_id"],)).fetchone()[0]
        if patient_name:
            return jsonify(reply=f"Appointment #{aid} cancelled. The {display_time(appointment['appointment_time'])} slot on {appointment['appointment_date']} with {doctor_name} was offered to {patient_name}. Review and approve the offer in Waitlist Management.", action="cancel", waitlist_action="offered")
        return jsonify(reply=f"Appointment #{aid} with {doctor_name} was cancelled. No one is waiting for this doctor and date at {display_time(appointment['appointment_time'])}. Waitlist offers must match the doctor; patients with no preferred day can match any date.", action="cancel")

    asks_to_reschedule = any(phrase in lower for phrase in (
        "reschedule", "change appointment", "change my appointment",
        "move appointment", "move my appointment", "shift appointment",
        "postpone appointment", "change the appointment time",
    ))
    if asks_to_reschedule:
        match = re.search(r"appointment\s*#?\s*(\d+)", lower)
        if not match:
            return jsonify(reply="Please provide an appointment ID, for example: Reschedule appointment 2 to tomorrow at 11 AM.")
        aid, slot = int(match[1]), parse_time(message)
        if not slot:
            return jsonify(reply="Please specify the new time, for example: Reschedule appointment 2 to tomorrow at 11 AM.")
        try:
            with connection() as conn:
                appt = conn.execute("SELECT doctor_id FROM appointments WHERE appointment_id=? AND status='booked'", (aid,)).fetchone()
                if not appt:
                    return jsonify(reply=f"Active appointment #{aid} was not found.")
                if slot not in available_slots(appt["doctor_id"], day, aid):
                    slots = available_slots(appt["doctor_id"], day, aid)
                    return jsonify(reply=f"{display_time(slot)} is not available on {day}. Available slots: {', '.join(display_time(value) for value in slots) if slots else 'none'}.")
                conn.execute("UPDATE appointments SET appointment_date=?,appointment_time=?,booking_lead_days=? WHERE appointment_id=?", (day.isoformat(), slot, max(0,(day-date.today()).days),aid))
        except sqlite3.IntegrityError:
            return jsonify(reply="That slot has just been booked. Please choose another time.")
        return jsonify(reply=f"Appointment #{aid} rescheduled to {day} at {display_time(slot)}.", action="reschedule")

    if any(word in lower for word in ("book", "appointment", "schedule")):
        if not doctor:
            return jsonify(reply=doctor_choice_prompt(message) + " You can reply with a name, then tell me a day and time.")
        slot = parse_time(message)
        slots = available_slots(doctor["doctor_id"], day)
        if not slot:
            return jsonify(reply=f"What time works for you? For {doctor['name']} on {day}, available times are: {', '.join(display_time(value) for value in slots) if slots else 'none'}.", context=conversation_context(doctor, day))
        if slot not in slots:
            return jsonify(reply=f"{display_time(slot)} is not available with {doctor['name']} on {day}. Available times: {', '.join(display_time(value) for value in slots) if slots else 'none'}.", context=conversation_context(doctor, day))
        match = re.search(r"(?:name is|i am|i'm|for)\s+([A-Za-z]+(?:\s+[A-Za-z]+)*?)(?=\s+(?:tomorrow|today|at)\b|[.,!?]*$)", message, re.I)
        name = match[1].strip() if match else "Demo Patient"
        try:
            with connection() as conn:
                pid = get_or_create_patient(conn, name)
                conn.execute("INSERT INTO appointments(patient_id,doctor_id,appointment_date,appointment_time,booking_lead_days) VALUES(?,?,?,?,?)", (pid,doctor["doctor_id"],day.isoformat(),slot,max(0,(day-date.today()).days)))
                aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        except sqlite3.IntegrityError:
            return jsonify(reply="That slot was just booked. Please choose another time.")
        return jsonify(reply=f"Appointment confirmed! Booking ID #{aid}: {name} with {doctor['name']} on {day} at {display_time(slot)}.", action="book")

    if doctor:
        return jsonify(reply=f"{doctor['name']} works in {doctor['specialty']}. Would you like to check availability or book an appointment?", context=conversation_context(doctor, day))
    return jsonify(reply="I can check availability, book, cancel, reschedule, or add patients to a waitlist. Tell me what you need in your own words, such as ‘Can I see a skin doctor tomorrow?’")


@app.post("/api/remind/<int:aid>")
def remind(aid):
    with connection() as conn:
        appt = conn.execute("""SELECT a.appointment_id,p.name AS patient,d.name AS doctor,a.appointment_date,a.appointment_time
            FROM appointments a JOIN patients p USING(patient_id) JOIN doctors d USING(doctor_id)
            WHERE a.appointment_id=? AND a.status='booked'""", (aid,)).fetchone()
        if not appt:
            return jsonify(ok=False,message="Active appointment not found."),404
        message = f"Reminder for {appt['patient']}: appointment with {appt['doctor']} on {appt['appointment_date']} at {display_time(appt['appointment_time'])}."
        conn.execute("INSERT INTO reminders(appointment_id,message) VALUES(?,?)",(aid,message))
    return jsonify(ok=True,message="SIMULATED reminder: "+message)


@app.get("/api/report")
def report():
    requested = request.args.get("date", date.today().isoformat())
    try:
        report_date = date.fromisoformat(requested)
    except (TypeError, ValueError):
        return jsonify(message="Choose a valid report date in YYYY-MM-DD format."), 400
    with connection() as conn:
        counts = conn.execute("""SELECT SUM(status='booked') AS booked,SUM(status='cancelled') AS cancelled
            FROM appointments WHERE appointment_date=?""", (report_date.isoformat(),)).fetchone()
        doctor_rows = conn.execute("""SELECT d.doctor_id,d.name AS doctor,d.specialty,
            SUM(CASE WHEN a.status='booked' THEN 1 ELSE 0 END) AS booked
            FROM doctors d LEFT JOIN appointments a ON a.doctor_id=d.doctor_id
                AND a.appointment_date=?
            WHERE d.available=1 GROUP BY d.doctor_id ORDER BY d.specialty,d.name""",
            (report_date.isoformat(),)).fetchall()
        rows = conn.execute("""SELECT a.appointment_id,p.name AS patient,d.name AS doctor,a.attended_before,a.booking_lead_days
            FROM appointments a JOIN patients p USING(patient_id) JOIN doctors d USING(doctor_id)
            WHERE a.status='booked' AND a.appointment_date=?""", (report_date.isoformat(),)).fetchall()
    capacity = len(doctor_rows) * len(SLOT_TIMES)
    booked_today = counts["booked"] or 0
    utilisation = round(booked_today * 100 / capacity, 1) if capacity else 0
    utilisation_by_doctor = []
    for row in doctor_rows:
        booked = row["booked"] or 0
        utilisation_by_doctor.append({
            "doctor": row["doctor"], "specialty": row["specialty"],
            "booked": booked, "capacity": len(SLOT_TIMES),
            "utilisation_pct": round(booked * 100 / len(SLOT_TIMES), 1),
        })
    risks = []
    for row in rows:
        score, reason = risk_score(row["attended_before"], row["booking_lead_days"])
        risks.append(dict(id=row["appointment_id"],patient=row["patient"],doctor=row["doctor"],score=score,reason=reason))
    return jsonify(date=report_date.isoformat(), booked=booked_today,
                   cancelled=counts["cancelled"] or 0, capacity=capacity,
                   utilisation_pct=utilisation, utilisation_by_doctor=utilisation_by_doctor,
                   risk=risks,
                   utilisation_note="Booked slots divided by seven demo appointment slots per doctor. This is a scheduling estimate, not a clinical metric.")


@app.post("/api/reschedule")
def reschedule():
    data = json_body()
    try:
        aid = int(data.get("id", 0))
        new_date = date.fromisoformat(data.get("date", ""))
    except (ValueError, TypeError):
        return jsonify(ok=False,message="Provide a valid appointment ID and date (YYYY-MM-DD)."),400
    new_time = data.get("time")
    if not isinstance(new_time,str) or new_time not in SLOT_TIMES:
        return jsonify(ok=False,message="Choose a valid clinic appointment time."),400
    try:
        with connection() as conn:
            appt = conn.execute("SELECT doctor_id FROM appointments WHERE appointment_id=? AND status='booked'",(aid,)).fetchone()
            if not appt:
                return jsonify(ok=False,message="Active appointment not found."),404
            if new_time not in available_slots(appt["doctor_id"],new_date,aid):
                return jsonify(ok=False,message="That slot is not available."),409
            conn.execute("UPDATE appointments SET appointment_date=?,appointment_time=?,booking_lead_days=? WHERE appointment_id=?",(new_date.isoformat(),new_time,max(0,(new_date-date.today()).days),aid))
    except sqlite3.IntegrityError:
        return jsonify(ok=False,message="That slot has just been booked. Please choose another time."),409
    return jsonify(ok=True,message=f"Appointment #{aid} rescheduled to {new_date} at {display_time(new_time)}.")


init_db()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
