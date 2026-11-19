# CareSlot MVP

A hackathon-ready clinic appointment coordination prototype using Flask, SQLite and vanilla HTML/CSS/JS.

## Run locally
1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Create a virtual environment (optional but recommended):
   - Windows: `py -m venv .venv`
   - Windows PowerShell: `.venv\\Scripts\\Activate.ps1`
4. Install dependencies: `pip install -r requirements.txt`
5. Start: `python app.py`
6. Open http://127.0.0.1:5000

The database and fictional sample records are created automatically on first run.

## Demo prompts
- `Show Dr. Kumar availability tomorrow`
- `Book Dr. Priya tomorrow at 3 PM for Meera Das`
- `Add me to Dr. Shah waitlist`
- `Cancel appointment 1`

## Included
- Doctor schedule and availability lookup
- Appointment booking
- Cancellation by appointment ID
- Waitlist entry
- Simulated reminders
- Explainable no-show risk heuristic
- Daily summary dashboard

## Important prototype limitations
- Uses synthetic/demo patient data only.
- Reminder messages are simulated; no SMS/email is sent.
- No-show risk is a transparent rule-based demo estimate, not a validated prediction model.
- The natural-language parser is a lightweight demo parser, not a full LLM. Add an LLM tool-calling layer only after the core workflow is stable.
- Overbooking is not implemented; any real overbooking policy must require front-desk approval.
- This is administrative software and does not provide medical advice.
