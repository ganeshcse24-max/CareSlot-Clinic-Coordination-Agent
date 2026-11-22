"""SQLite storage and schema for the CareSlot demo."""
from contextlib import contextmanager
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("CARESLOT_DB", Path(__file__).with_name("careslot.db")))


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def connection():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS doctors (
            doctor_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            specialty TEXT NOT NULL,
            available INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS patients (
            patient_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            phone TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS appointments (
            appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(patient_id),
            doctor_id INTEGER NOT NULL REFERENCES doctors(doctor_id),
            appointment_date TEXT NOT NULL,
            appointment_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'booked' CHECK(status IN ('booked','cancelled')),
            attended_before INTEGER NOT NULL DEFAULT 1 CHECK(attended_before IN (0,1)),
            booking_lead_days INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS unique_active_doctor_slot
            ON appointments(doctor_id, appointment_date, appointment_time) WHERE status='booked';
        CREATE TABLE IF NOT EXISTS waitlist (
            waitlist_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(patient_id),
            doctor_id INTEGER NOT NULL REFERENCES doctors(doctor_id),
            preferred_date TEXT,
            preferred_time TEXT,
            offered_date TEXT,
            offered_time TEXT,
            status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','offered','accepted','rejected')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reminders (
            reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL REFERENCES appointments(appointment_id),
            message TEXT NOT NULL,
            delivery_status TEXT NOT NULL DEFAULT 'simulated',
            sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.executemany(
            "INSERT OR IGNORE INTO doctors(name,specialty) VALUES(?,?)",
            [
                ("Dr. Kumar", "General Medicine"),
                ("Dr. Arjun Rao", "General Medicine"),
                ("Dr. Kavita Menon", "General Medicine"),
                ("Dr. Priya", "Dermatology"),
                ("Dr. Neha Iyer", "Dermatology"),
                ("Dr. Vivek Nair", "Dermatology"),
                ("Dr. Shah", "Cardiology"),
                ("Dr. Rohan Mehta", "Cardiology"),
                ("Dr. Anil Reddy", "Cardiology"),
            ],
        )
        # Keep existing demo installations aligned with the bundled directory.
        conn.execute("UPDATE doctors SET specialty='General Medicine' WHERE name='Dr. Kumar'")
        # Older versions treated an omitted waitlist date as today's date.
        # Convert those legacy defaults to an open date preference once.
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if schema_version < 2:
            conn.execute("UPDATE waitlist SET preferred_date=NULL WHERE status='waiting' AND preferred_date=date(created_at)")
        waitlist_columns = {row[1] for row in conn.execute("PRAGMA table_info(waitlist)")}
        if "offered_date" not in waitlist_columns:
            conn.execute("ALTER TABLE waitlist ADD COLUMN offered_date TEXT")
        if "offered_time" not in waitlist_columns:
            conn.execute("ALTER TABLE waitlist ADD COLUMN offered_time TEXT")
        if schema_version < 3:
            conn.execute("UPDATE waitlist SET offered_date=preferred_date,offered_time=preferred_time WHERE status='offered'")
            conn.execute("PRAGMA user_version=3")
        conn.executemany(
            "INSERT OR IGNORE INTO patients(name,phone) VALUES(?,?)",
            [("Rahul Sharma", "9000000001"), ("Ananya Rao", "9000000002"), ("Aarav Nair", "9000000003"), ("Meera Das", "9000000004")],
        )
        if conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 0:
            tomorrow = (date_today() + timedelta(days=1)).isoformat()
            doctor_ids = {row["name"]: row["doctor_id"] for row in conn.execute("SELECT doctor_id,name FROM doctors")}
            patient_ids = {row["name"]: row["patient_id"] for row in conn.execute("SELECT patient_id,name FROM patients")}
            conn.executemany("""INSERT INTO appointments
                (patient_id,doctor_id,appointment_date,appointment_time,status,attended_before,booking_lead_days)
                VALUES(?,?,?,?,?,?,?)""", [
                (patient_ids["Rahul Sharma"], doctor_ids["Dr. Kumar"], tomorrow, "09:00", "booked", 1, 2),
                (patient_ids["Ananya Rao"], doctor_ids["Dr. Kumar"], tomorrow, "10:00", "booked", 0, 5),
                (patient_ids["Aarav Nair"], doctor_ids["Dr. Priya"], tomorrow, "11:00", "booked", 1, 1),
                (patient_ids["Meera Das"], doctor_ids["Dr. Shah"], tomorrow, "12:00", "booked", 1, 3),
            ])


def date_today():
    from datetime import date
    return date.today()


from datetime import timedelta
