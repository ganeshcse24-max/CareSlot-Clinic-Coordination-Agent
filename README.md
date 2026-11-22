# CareSlot

A clinic appointment coordination prototype using Flask, SQLite and vanilla HTML/CSS/JavaScript. It uses fictional sample records and runs without a separate database server.

## Run locally
1. Install Python 3.10 or later.
2. Open a terminal in this folder.
3. Create a virtual environment (optional but recommended):
   - Windows: `py -m venv .venv`
   - Windows PowerShell: `.venv\Scripts\Activate.ps1`
4. Install dependencies: `pip install -r requirements.txt`
5. Start: `python app.py`
6. Open http://127.0.0.1:5000

The SQLite database (`careslot.db` by default) and fictional sample records are created automatically on first run. Set `CARESLOT_DB` to use a different database file. Keep the database file private because it can contain patient names, even in this demo.

## Demo prompts
- `Show Dr. Kumar availability tomorrow`
- `Book Dr. Priya tomorrow at 3 PM for Meera Das`
- You can also book in short turns: `Book an appointment` → `Dr. Priya` → `tomorrow at 3 for Meera Das`.
- Try a department such as `skin doctor`; the assistant will show its doctors.
- `Add me to Dr. Shah waitlist`
- `Cancel appointment 1`
- `Move appointment 2 to Friday at 11 AM`

## Included
- Doctor schedule and availability lookup
- Nine demo doctors across General Medicine, Dermatology and Cardiology (three per department)
- Appointment booking
- Cancellation by appointment ID
- Rescheduling and waitlist offer approval
- Date and time-aware waitlist matching; open dates match the next compatible slot, then staff approves or rejects the offer
- Simulated reminders
- Explainable no-show risk estimates with contributing factors
- Daily utilisation by doctor and clinic, selectable by date
- Voice dictation in browsers that support Web Speech recognition and grant microphone access

## Verify the project

Run the included end-to-end workflow checks with:

```powershell
python -m unittest discover -s tests -v
```

## Important prototype limitations
- Uses synthetic/demo patient data only.
- Reminder messages are simulated; no SMS/email is sent.
- Voice dictation uses the browser's speech recognition support; typed requests work in every supported browser.
- No-show risk is a transparent rule-based demo estimate, not a validated prediction model.
- The natural-language parser is a lightweight intent parser, not a general-purpose LLM.
- Overbooking is blocked; any exception needs front-desk approval.
- This is administrative software and does not provide medical advice.

## Configuration

No PostgreSQL server or `.env` file is required. `CARESLOT_DB` is the only optional setting. The app binds to `127.0.0.1:5000` for local use. Do not expose this demo publicly: it has no login or role-based access controls.
