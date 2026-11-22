"""End-to-end checks for the CareSlot demo workflows."""
from datetime import date, timedelta
import os
from pathlib import Path
import tempfile
import unittest

_test_dir = tempfile.TemporaryDirectory(prefix="careslot-tests-")
os.environ["CARESLOT_DB"] = str(Path(_test_dir.name) / "test.db")

from app import app as flask_app  # noqa: E402
from db import connection  # noqa: E402

with connection() as _conn:
    _seeded_specialties = {
        row[0] for row in _conn.execute("""SELECT DISTINCT d.specialty FROM appointments a
            JOIN doctors d USING(doctor_id) WHERE a.status='booked'""")
    }


class CareSlotWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.client = flask_app.test_client()
        self.tomorrow = date.today() + timedelta(days=1)
        with connection() as conn:
            conn.execute("DELETE FROM reminders")
            conn.execute("DELETE FROM waitlist")
            conn.execute("DELETE FROM appointments")
            doctor_id = conn.execute("SELECT doctor_id FROM doctors WHERE name='Dr. Kumar'").fetchone()[0]
            patient_id = conn.execute("SELECT patient_id FROM patients WHERE name='Rahul Sharma'").fetchone()[0]
            conn.execute("""INSERT INTO appointments
                (patient_id,doctor_id,appointment_date,appointment_time,attended_before,booking_lead_days)
                VALUES(?,?,?,?,?,?)""",
                (patient_id, doctor_id, self.tomorrow.isoformat(), "09:00", 0, 5))
            self.appointment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def test_home_and_department_directory(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        doctors = self.client.get("/api/doctors").get_json()["doctors"]
        self.assertEqual(len(doctors), 9)
        counts = {}
        for doctor in doctors:
            counts[doctor["specialty"]] = counts.get(doctor["specialty"], 0) + 1
        self.assertEqual(set(counts.values()), {3})
        self.assertTrue({"Dermatology", "Cardiology"}.issubset(_seeded_specialties))

    def test_chat_booking_uses_ampm_and_blocks_double_booking(self):
        booking = self.client.post("/api/chat", json={
            "message": "Book Dr. Priya tomorrow at 3 PM for Meera Das"
        }).get_json()
        self.assertEqual(booking["action"], "book")
        self.assertIn("3:00 PM", booking["reply"])
        conflict = self.client.post("/api/chat", json={
            "message": "Book Dr. Kumar tomorrow at 9 AM for Ananya Rao"
        }).get_json()
        self.assertIn("not available", conflict["reply"])

    def test_waitlist_offer_survives_refresh_and_requires_approval(self):
        added = self.client.post("/api/chat", json={
            "message": "Add Test Patient to Dr. Kumar waitlist"
        }).get_json()
        self.assertEqual(added["action"], "waitlist")
        waiting = self.client.get("/api/waitlist").get_json()["waitlist"][0]
        self.assertIsNone(waiting["preferred_date"])

        cancelled = self.client.post("/api/chat", json={
            "message": f"Cancel appointment {self.appointment_id}"
        }).get_json()
        self.assertEqual(cancelled["waitlist_action"], "offered")
        before_approval = self.client.get("/api/dashboard").get_json()
        self.assertEqual(before_approval["booked"], 0)
        self.assertEqual(before_approval["cancelled"], 1)
        refreshed = self.client.get("/api/waitlist").get_json()["waitlist"][0]
        self.assertEqual(refreshed["status"], "offered")
        self.assertEqual(refreshed["preferred_date"], self.tomorrow.isoformat())
        self.assertEqual(refreshed["preferred_time"], "9:00 AM")

        approved = self.client.post(f"/api/waitlist/{refreshed['waitlist_id']}/approve")
        self.assertEqual(approved.status_code, 200)
        self.assertIn("approved", approved.get_json()["message"])
        after_approval = self.client.get("/api/dashboard").get_json()
        self.assertEqual(after_approval["booked"], 1)
        self.assertEqual(after_approval["cancelled"], 1)

    def test_reschedule_reminder_and_daily_utilisation_report(self):
        rescheduled = self.client.post("/api/reschedule", json={
            "id": self.appointment_id,
            "date": (date.today() + timedelta(days=2)).isoformat(),
            "time": "14:00",
        })
        self.assertEqual(rescheduled.status_code, 200)
        self.assertIn("2:00 PM", rescheduled.get_json()["message"])

        move_request = self.client.post("/api/chat", json={
            "message": f"Move appointment {self.appointment_id} to {(date.today() + timedelta(days=2)).isoformat()} at 3 PM"
        }).get_json()
        self.assertEqual(move_request["action"], "reschedule")
        self.assertIn("3:00 PM", move_request["reply"])

        reminder = self.client.post(f"/api/remind/{self.appointment_id}")
        self.assertEqual(reminder.status_code, 200)
        self.assertIn("SIMULATED", reminder.get_json()["message"])
        self.assertIn("3:00 PM", reminder.get_json()["message"])

        report_day = date.today() + timedelta(days=2)
        report = self.client.get("/api/report?date=" + report_day.isoformat()).get_json()
        self.assertEqual(report["booked"], 1)
        self.assertEqual(report["capacity"], 63)
        self.assertEqual(report["utilisation_pct"], 1.6)
        self.assertEqual(len(report["utilisation_by_doctor"]), 9)
        self.assertEqual(len(report["risk"]), 1)
        self.assertEqual(report["risk"][0]["score"], 65)
        self.assertIn("previous missed appointment", report["risk"][0]["reason"])

    def test_rejecting_an_offer_restores_original_preferences(self):
        with connection() as conn:
            doctor_id = conn.execute("SELECT doctor_id FROM doctors WHERE name='Dr. Kumar'").fetchone()[0]
            patient_id = conn.execute("SELECT patient_id FROM patients WHERE name='Meera Das'").fetchone()[0]
            conn.execute("""INSERT INTO appointments
                (patient_id,doctor_id,appointment_date,appointment_time)
                VALUES(?,?,?,?)""", (patient_id, doctor_id, self.tomorrow.isoformat(), "10:00"))
            second_appointment = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        added = self.client.post("/api/chat", json={
            "message": "Join Dr. Kumar waitlist. My name is Meera Das for tomorrow at 10 AM"
        }).get_json()
        self.assertEqual(added["action"], "waitlist")
        cancelled = self.client.post("/api/chat", json={
            "message": f"Cancel appointment {second_appointment}"
        }).get_json()
        self.assertEqual(cancelled["waitlist_action"], "offered")
        entry = self.client.get("/api/waitlist").get_json()["waitlist"][0]
        rejected = self.client.post(f"/api/waitlist/{entry['waitlist_id']}/reject")
        self.assertEqual(rejected.status_code, 200)
        returned = self.client.get("/api/waitlist").get_json()["waitlist"][0]
        self.assertEqual(returned["status"], "waiting")
        self.assertEqual(returned["preferred_date"], self.tomorrow.isoformat())
        self.assertEqual(returned["preferred_time"], "10:00 AM")

    def test_voice_controls_are_in_the_served_page(self):
        page = self.client.get("/").get_data(as_text=True)
        script_response = self.client.get("/static/app.js")
        script = script_response.get_data(as_text=True)
        script_response.close()
        self.assertIn('id="voiceButton"', page)
        self.assertIn("SpeechRecognition", script)
        self.assertIn("recognition.onresult", script)

    def test_greeting_and_invalid_report_date(self):
        greeting = self.client.post("/api/chat", json={"message": "hello"}).get_json()
        self.assertTrue(greeting["reply"].startswith("Hello!"))
        self.assertEqual(self.client.get("/api/report?date=not-a-date").status_code, 400)


if __name__ == "__main__":
    unittest.main()
