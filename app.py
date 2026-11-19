
from flask import Flask, render_template, request, jsonify
from psycopg2.extras import RealDictCursor
from datetime import date, timedelta
import re
from db import get_connection

app = Flask(__name__)


# ==========================================
# DATABASE HELPER
# ==========================================

def run_query(sql, params=(), fetch="all"):
    conn = get_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)

            if fetch == "one":
                result = cur.fetchone()
            elif fetch == "none":
                result = None
            else:
                result = cur.fetchall()

        conn.commit()

        if fetch == "none":
            return None

        return dict(result) if fetch == "one" and result else (
            [dict(row) for row in result]
            if fetch == "all" and result is not None else None
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# ==========================================
# SAMPLE DATA
# ==========================================

def init_sample_data():

    for name, specialty in [
        ("Dr. Kumar", "General Physician"),
        ("Dr. Priya", "Dermatology"),
        ("Dr. Shah", "Cardiology")
    ]:
        run_query(
            "INSERT INTO doctors(name,specialty) "
            "VALUES(%s,%s) ON CONFLICT(name) DO NOTHING",
            (name, specialty),
            "none"
        )

    for name, phone in [
        ("Rahul Sharma", "9000000001"),
        ("Ananya Rao", "9000000002"),
        ("Aarav Nair", "9000000003"),
        ("Meera Das", "9000000004")
    ]:
        run_query(
            "INSERT INTO patients(name,phone) "
            "VALUES(%s,%s) ON CONFLICT(phone) DO NOTHING",
            (name, phone),
            "none"
        )


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def find_doctor(text):

    doctors = run_query(
        "SELECT doctor_id,name FROM doctors WHERE available=TRUE"
    )

    lower = text.lower()

    for doctor in doctors:
        if (
            doctor["name"].lower() in lower
            or doctor["name"].split()[-1].lower() in lower
        ):
            return doctor

    return None


def requested_date(text):

    lower = text.lower()

    if "day after tomorrow" in lower:
        return date.today() + timedelta(days=2)

    if "tomorrow" in lower:
        return date.today() + timedelta(days=1)

    return date.today()


def available_slots(doctor_id, day):

    rows = run_query(
        """
        SELECT appointment_time
        FROM appointments
        WHERE doctor_id=%s
        AND appointment_date=%s
        AND status='booked'
        """,
        (doctor_id, day)
    )

    booked = {
        row["appointment_time"].strftime("%H:%M")
        for row in rows
    }

    return [
        t for t in [
            "09:00", "10:00", "11:00",
            "12:00", "14:00", "15:00", "16:00"
        ]
        if t not in booked
    ]



def parse_time(text):
    # Convert spoken time formats such as p.m. and a.m.
    text = text.lower().strip()

    text = re.sub(
        r"\b([ap])\s*\.?\s*m\.?\b",
        r"\1m",
        text
    )

    # Match 2 PM, 2:00 PM, 2 p.m., etc.
    match = re.search(
        r"\b(9|10|11|12|1|2|3|4)(?::([0-5]\d))?\s*(am|pm)\b",
        text
    )

    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        period = match.group(3)

        if period == "pm" and hour != 12:
            hour += 12

        elif period == "am" and hour == 12:
            hour = 0

        return f"{hour:02d}:{minute:02d}"

    # Match 24-hour format such as 14:00
    match = re.search(
        r"\b(09|10|11|12|14|15|16):([0-5]\d)\b",
        text
    )

    if match:
        return f"{match.group(1)}:{match.group(2)}"

    return None



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

    return (
        min(score, 95),
        ", ".join(reasons) if reasons
        else "no major demo risk factors"
    )


# ==========================================
# HOME
# ==========================================

@app.route("/")
def home():
    return render_template("index.html")


# ==========================================
# WAITLIST API
# ==========================================

@app.route("/api/waitlist")
def get_waitlist():

    rows = run_query("""
        SELECT
            w.waitlist_id,
            p.name AS patient,
            d.name AS doctor,
            w.preferred_date,
            w.preferred_time,
            w.status
        FROM waitlist w
        JOIN patients p ON w.patient_id = p.patient_id
        JOIN doctors d ON w.doctor_id = d.doctor_id
        ORDER BY w.created_at DESC
    """)

    for row in rows:

        row["preferred_date"] = (
            row["preferred_date"].isoformat()
            if row["preferred_date"] else None
        )

        row["preferred_time"] = (
            row["preferred_time"].strftime("%H:%M")
            if row["preferred_time"] else None
        )

    return jsonify({"waitlist": rows})


# ==========================================
# APPROVE WAITLIST OFFER
# ==========================================

@app.route("/api/waitlist/<int:wid>/approve", methods=["POST"])
def approve_waitlist(wid):

    patient = run_query("""
        SELECT
            waitlist_id,
            patient_id,
            doctor_id,
            preferred_date,
            preferred_time
        FROM waitlist
        WHERE waitlist_id = %s
        AND status = 'offered'
    """, (wid,), "one")

    if not patient:
        return jsonify({
            "message": "No active offered waitlist entry found."
        }), 404

    if not patient["preferred_date"] or not patient["preferred_time"]:
        return jsonify({
            "message": "The offered appointment date or time is missing."
        }), 400

    # Check whether the slot is still available
    slots = available_slots(
        patient["doctor_id"],
        patient["preferred_date"]
    )

    slot = patient["preferred_time"].strftime("%H:%M")

    if slot not in slots:
        return jsonify({
            "message": "This appointment slot is no longer available."
        }), 409

    lead = max(
        0,
        (patient["preferred_date"] - date.today()).days
    )

    # Create confirmed appointment
    try:
        booking = run_query("""
            INSERT INTO appointments(
                patient_id,
                doctor_id,
                appointment_date,
                appointment_time,
                booking_lead_days
            )
            VALUES(%s,%s,%s,%s,%s)
            RETURNING appointment_id
        """, (
            patient["patient_id"],
            patient["doctor_id"],
            patient["preferred_date"],
            patient["preferred_time"],
            lead
        ), "one")

    except Exception as e:

        if (
            "unique_active_doctor_slot" in str(e)
            or "duplicate key" in str(e)
        ):
            return jsonify({
                "message": "This appointment slot has already been booked."
            }), 409

        raise

    # Mark waitlist entry as accepted
    run_query("""
        UPDATE waitlist
        SET status = 'accepted'
        WHERE waitlist_id = %s
        AND status = 'offered'
    """, (wid,), "none")

    return jsonify({
        "message": (
            f"Appointment approved successfully! "
            f"New appointment ID: #{booking['appointment_id']}."
        )
    })


# ==========================================
# REJECT WAITLIST OFFER
# ==========================================

@app.route("/api/waitlist/<int:wid>/reject", methods=["POST"])
def reject_waitlist(wid):

    result = run_query("""
        UPDATE waitlist
        SET status = 'waiting',
            preferred_time = NULL
        WHERE waitlist_id = %s
        AND status = 'offered'
        RETURNING waitlist_id
    """, (wid,), "one")

    if not result:
        return jsonify({
            "message": "No active offered waitlist entry found."
        }), 404

    return jsonify({
        "message": (
            "Offer rejected. Patient returned to the waiting list."
        )
    })


# ==========================================
# DASHBOARD API
# ==========================================

@app.route("/api/dashboard")
def dashboard():

    rows = run_query("""
        SELECT
            a.appointment_id AS id,
            a.appointment_date,
            a.appointment_time,
            a.status,
            p.name AS patient,
            d.name AS doctor,
            d.specialty
        FROM appointments a
        JOIN patients p ON p.patient_id = a.patient_id
        JOIN doctors d ON d.doctor_id = a.doctor_id
        ORDER BY a.appointment_date, a.appointment_time
    """)

    appointments = []

    for r in rows:
        r["appt_date"] = r.pop("appointment_date").isoformat()
        r["appt_time"] = r.pop("appointment_time").strftime("%H:%M")
        appointments.append(r)

    waiting = run_query(
        "SELECT COUNT(*) AS n FROM waitlist WHERE status='waiting'",
        fetch="one"
    )["n"]

    today = date.today().isoformat()

    return jsonify({
        "appointments": appointments,
        "total": sum(
            1 for a in appointments
            if a["appt_date"] >= today and a["status"] == "booked"
        ),
        "booked": sum(
            1 for a in appointments if a["status"] == "booked"
        ),
        "cancelled": sum(
            1 for a in appointments if a["status"] == "cancelled"
        ),
        "waitlist": waiting
    })


# ==========================================
# CHAT API
# ==========================================

@app.route("/api/chat", methods=["POST"])
def chat():

    message = (request.json or {}).get("message", "").strip()

    if not message:
        return jsonify({"reply": "Please enter a request."})

    lower = message.lower()
    doctor = find_doctor(message)
    day = requested_date(message)

    # CHECK AVAILABILITY
    if any(w in lower for w in [
        "available", "availability", "free slot", "slots"
    ]):

        if not doctor:
            return jsonify({
                "reply": "Which doctor? Try Dr. Kumar, Dr. Priya or Dr. Shah."
            })

        slots = available_slots(doctor["doctor_id"], day)

        return jsonify({
            "reply": (
                f"{doctor['name']} has these available slots on {day}: "
                f"{', '.join(slots) if slots else 'No slots available'}."
            ),
            "action": "availability"
        })

    
    # JOIN WAITLIST
    if "waitlist" in lower or "waiting list" in lower:

        if not doctor:
            return jsonify({
                "reply": "Which doctor's waitlist? Try Dr. Kumar, Dr. Priya or Dr. Shah."
            })

        # Extract patient's name
        m = re.search(
            r"(?:name is|i am|i'm)\s+([A-Za-z]+(?:\s+[A-Za-z]+)*?)(?=\s+(?:for|tomorrow|today|at)\b|[.,!?]*$)",
            message,
            re.I
        )

        if not m:
            return jsonify({
                "reply": (
                    "Please provide your name. Example: "
                    "Join Dr. Kumar's waitlist. My name is Rahul Sharma."
                )
            })

        pname = m.group(1).strip()

        # Extract preferred appointment time
        preferred_time = parse_time(message)

        # Find or create patient
        patient = run_query(
            "SELECT patient_id FROM patients WHERE lower(name)=lower(%s)",
            (pname,),
            "one"
        )

        if not patient:
            patient = run_query(
                "INSERT INTO patients(name) VALUES(%s) RETURNING patient_id",
                (pname,),
                "one"
            )

        # Add patient with preferred date and time
        run_query("""
            INSERT INTO waitlist(
                patient_id,
                doctor_id,
                preferred_date,
                preferred_time
            )
            VALUES(%s,%s,%s,%s)
        """, (
            patient["patient_id"],
            doctor["doctor_id"],
            day,
            preferred_time
        ), "none")

        time_message = (
            f" at {preferred_time}"
            if preferred_time
            else " (no specific time requested)"
        )

        return jsonify({
            "reply": (
                f"{pname} has been added to {doctor['name']}'s "
                f"waitlist for {day}{time_message}. "
                f"This is simulated."
            ),
            "action": "waitlist"
        })


    
    # CANCEL APPOINTMENT AND OFFER SLOT
    if "cancel" in lower:

        m = re.search(
            r"(?:appointment\s*)?#?\s*(\d+)",
            lower
        )

        if not m:
            return jsonify({
                "reply": (
                    "Please include an appointment ID, "
                    "for example: cancel appointment 2."
                )
            })

        aid = int(m.group(1))

        appointment = run_query("""
            SELECT
                appointment_id,
                doctor_id,
                appointment_date,
                appointment_time
            FROM appointments
            WHERE appointment_id = %s
            AND status = 'booked'
        """, (aid,), "one")

        if not appointment:
            return jsonify({
                "reply": f"No active appointment #{aid} found."
            })

        run_query("""
            UPDATE appointments
            SET status = 'cancelled'
            WHERE appointment_id = %s
        """, (aid,), "none")

        # PRIORITY-BASED WAITLIST MATCHING
        # 1. Exact preferred time
        # 2. No preferred time specified
        # 3. Earlier waitlist entry wins when priorities are equal

        waiting_patient = run_query("""
            SELECT waitlist_id, patient_id
            FROM waitlist
            WHERE doctor_id = %s
            AND preferred_date = %s
            AND status = 'waiting'
            AND (
                preferred_time IS NULL
                OR preferred_time = %s
            )
            ORDER BY
                CASE
                    WHEN preferred_time = %s THEN 0
                    WHEN preferred_time IS NULL THEN 1
                    ELSE 2
                END,
                created_at ASC,
                waitlist_id ASC
            LIMIT 1
        """, (
            appointment["doctor_id"],
            appointment["appointment_date"],
            appointment["appointment_time"],
            appointment["appointment_time"]
        ), "one")

        if waiting_patient:

            # Save the exact offered appointment slot
            run_query("""
                UPDATE waitlist
                SET status = 'offered',
                    preferred_date = %s,
                    preferred_time = %s
                WHERE waitlist_id = %s
            """, (
                appointment["appointment_date"],
                appointment["appointment_time"],
                waiting_patient["waitlist_id"]
            ), "none")

            patient = run_query("""
                SELECT name
                FROM patients
                WHERE patient_id = %s
            """, (waiting_patient["patient_id"],), "one")

            return jsonify({
                "reply": (
                    f"Appointment #{aid} cancelled successfully. "
                    f"The available slot has been offered to "
                    f"{patient['name']} from the waitlist. "
                    f"Front-desk confirmation is required."
                ),
                "action": "cancel",
                "waitlist_action": "offered"
            })

        return jsonify({
            "reply": (
                f"Appointment #{aid} cancelled successfully. "
                "No matching patient was found in the waitlist."
            ),
            "action": "cancel"
        })


    # RESCHEDULE APPOINTMENT THROUGH CHAT
    if "reschedule" in lower or "change appointment" in lower:

        m = re.search(
            r"appointment\s*#?\s*(\d+)",
            lower
        )

        if not m:
            return jsonify({
                "reply": "Please provide the appointment ID. Example: Reschedule appointment 2 to tomorrow at 11 AM."
            })

        aid = int(m.group(1))

        # Find existing active appointment
        appointment = run_query("""
            SELECT appointment_id, doctor_id,
                   appointment_date, appointment_time
            FROM appointments
            WHERE appointment_id = %s
            AND status = 'booked'
        """, (aid,), "one")

        if not appointment:
            return jsonify({
                "reply": f"Active appointment #{aid} was not found."
            })

        # Extract new date and time
        new_date = requested_date(message)
        new_time = parse_time(message)

        if not new_time:
            return jsonify({
                "reply": "Please specify the new time, for example: Reschedule appointment 2 to tomorrow at 11 AM."
            })

        # Check availability
        slots = available_slots(
            appointment["doctor_id"],
            new_date
        )

        if new_time not in slots:
            return jsonify({
                "reply": (
                    f"{new_time} is not available on {new_date}. "
                    f"Available slots: "
                    f"{', '.join(slots) if slots else 'none'}."
                )
            })

        # Update appointment
        new_lead = max(
            0,
            (new_date - date.today()).days
        )

        try:
            run_query("""
                UPDATE appointments
                SET appointment_date = %s,
                    appointment_time = %s,
                    booking_lead_days = %s
                WHERE appointment_id = %s
            """, (
                new_date,
                new_time,
                new_lead,
                aid
            ), "none")

        except Exception as e:
            if "duplicate key" in str(e):
                return jsonify({
                    "reply": "That slot has just been booked. Please choose another time."
                })
            raise

        return jsonify({
            "reply": (
                f"Appointment #{aid} rescheduled successfully! "
                f"Your new appointment is on {new_date} "
                f"at {new_time}."
            ),
            "action": "reschedule"
        })

    # BOOK APPOINTMENT
    if any(w in lower for w in [
        "book", "appointment", "schedule"
    ]):

        if not doctor:
            return jsonify({
                "reply": "Which doctor? Mention Dr. Kumar, Dr. Priya or Dr. Shah."
            })

        appt_time = parse_time(message)

        if not appt_time:
            slots = available_slots(doctor["doctor_id"], day)

            return jsonify({
                "reply": (
                    f"Please specify a time. Available for {doctor['name']} "
                    f"on {day}: {', '.join(slots) if slots else 'none'}."
                )
            })

        slots = available_slots(doctor["doctor_id"], day)

        if appt_time not in slots:
            return jsonify({
                "reply": (
                    f"{appt_time} is not available with {doctor['name']} "
                    f"on {day}. Available: "
                    f"{', '.join(slots) if slots else 'none'}."
                )
            })

        m = re.search(
            r"(?:name is|i am|i'm|for)\s+([A-Za-z ]+?)(?:\s+(?:tomorrow|today|at)\b|[.,!?]*$)",
            message,
            re.I
        )

        pname = m.group(1).strip() if m else "Demo Patient"

        patient = run_query(
            "SELECT patient_id FROM patients WHERE lower(name)=lower(%s)",
            (pname,),
            "one"
        )

        if not patient:
            patient = run_query(
                "INSERT INTO patients(name) VALUES(%s) RETURNING patient_id",
                (pname,),
                "one"
            )

        lead = max(0, (day - date.today()).days)

        try:
            booking = run_query("""
                INSERT INTO appointments(
                    patient_id,
                    doctor_id,
                    appointment_date,
                    appointment_time,
                    booking_lead_days
                )
                VALUES(%s,%s,%s,%s,%s)
                RETURNING appointment_id
            """, (
                patient["patient_id"],
                doctor["doctor_id"],
                day,
                appt_time,
                lead
            ), "one")

        except Exception as e:

            if (
                "unique_active_doctor_slot" in str(e)
                or "duplicate key" in str(e)
            ):
                return jsonify({
                    "reply": "That slot was just booked. Please choose another time."
                })

            raise

        return jsonify({
            "reply": (
                f"Appointment confirmed! Booking ID "
                f"#{booking['appointment_id']}: {pname} with "
                f"{doctor['name']} on {day} at {appt_time}."
            ),
            "action": "book"
        })

    return jsonify({
        "reply": (
            "I can check availability, book, cancel and add "
            "patients to a waitlist. Example: Book Dr. Kumar "
            "tomorrow at 2 PM for Rahul Sharma."
        )
    })


# ==========================================
# SIMULATED REMINDER
# ==========================================

@app.route("/api/remind/<int:aid>", methods=["POST"])
def remind(aid):

    a = run_query("""
        SELECT
            a.appointment_id,
            p.name AS patient,
            d.name AS doctor,
            a.appointment_date,
            a.appointment_time
        FROM appointments a
        JOIN patients p ON p.patient_id = a.patient_id
        JOIN doctors d ON d.doctor_id = a.doctor_id
        WHERE a.appointment_id = %s
        AND a.status = 'booked'
    """, (aid,), "one")

    if not a:
        return jsonify({
            "ok": False,
            "message": "Active appointment not found."
        }), 404

    msg = (
        f"Reminder for {a['patient']}: appointment with "
        f"{a['doctor']} on {a['appointment_date']} "
        f"at {a['appointment_time']}."
    )

    run_query("""
        INSERT INTO reminders(
            appointment_id,
            message,
            delivery_status
        )
        VALUES(%s,%s,'simulated')
    """, (aid, msg), "none")

    return jsonify({
        "ok": True,
        "message": "SIMULATED reminder: " + msg
    })


# ==========================================
# DAILY REPORT
# ==========================================

@app.route("/api/report")
def report():

    rows = run_query("""
        SELECT
            a.appointment_id,
            a.attended_before,
            a.booking_lead_days,
            p.name AS patient,
            d.name AS doctor
        FROM appointments a
        JOIN patients p ON p.patient_id = a.patient_id
        JOIN doctors d ON d.doctor_id = a.doctor_id
        WHERE a.status = 'booked'
    """)

    counts = run_query("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'booked') AS booked,
            COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled
        FROM appointments
    """, fetch="one")

    risks = []

    for r in rows:

        score, reason = risk_score(
            r["attended_before"],
            r["booking_lead_days"]
        )

        risks.append({
            "id": r["appointment_id"],
            "patient": r["patient"],
            "doctor": r["doctor"],
            "score": score,
            "reason": reason
        })

    return jsonify({
        "booked": counts["booked"],
        "cancelled": counts["cancelled"],
        "risk": risks,
        "utilisation_note": (
            "Explainable demo estimate using synthetic data; "
            "not a validated prediction model."
        )
    })


# ==========================================
# RESCHEDULE APPOINTMENT
# ==========================================

@app.route("/api/reschedule", methods=["POST"])
def reschedule():

    data = request.json or {}

    aid = int(data.get("id", 0))
    new_date = date.fromisoformat(data.get("date", ""))
    new_time = data.get("time", "")

    a = run_query("""
        SELECT doctor_id
        FROM appointments
        WHERE appointment_id = %s
        AND status = 'booked'
    """, (aid,), "one")

    if not a:
        return jsonify({
            "ok": False,
            "message": "Active appointment not found."
        }), 404

    if new_time not in available_slots(a["doctor_id"], new_date):
        return jsonify({
            "ok": False,
            "message": "That slot is not available."
        }), 409

    run_query("""
        UPDATE appointments
        SET appointment_date = %s,
            appointment_time = %s
        WHERE appointment_id = %s
    """, (new_date, new_time, aid), "none")

    return jsonify({
        "ok": True,
        "message": (
            f"Appointment #{aid} rescheduled to "
            f"{new_date} at {new_time}."
        )
    })


# ==========================================
# START APPLICATION
# ==========================================

if __name__ == "__main__":
    init_sample_data()
    app.run(debug=True, host="127.0.0.1", port=5000)
