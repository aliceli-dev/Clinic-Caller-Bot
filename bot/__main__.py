from pathlib import Path
import os
import sys

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

CLINIC_NUMBER = "+18054398008"
ROOT = Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "run":
        print("usage: python -m bot run scenarios/schedule_checkup.json")
        sys.exit(1)

    scenario_path = Path(sys.argv[2])
    if not scenario_path.is_absolute():
        scenario_path = ROOT / scenario_path
    if not scenario_path.exists():
        print("cannot find", scenario_path)
        sys.exit(1)

    name = scenario_path.stem
    host = os.getenv("PUBLIC_HOST", "").strip()
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()
    if not host or not sid or not token or not from_number:
        print("fill TWILIO_* and PUBLIC_HOST in .env first")
        sys.exit(1)

    # Webhook URL: Twilio will fetch this URL when the clinic picks up.
    twiml_url = f"https://{host}/twiml?scenario={name}"
    recording_url = f"https://{host}/recording?scenario={name}"

    client = Client(sid, token)
    call = client.calls.create(
        to=CLINIC_NUMBER,
        from_=from_number,
        url=twiml_url,
        method="POST",
        record=True,
        recording_channels="dual",
        recording_status_callback=recording_url,
        recording_status_callback_method="POST",
        recording_status_callback_event=["completed"],
    )
    print("calling", CLINIC_NUMBER, "as", name)
    print("call sid", call.sid)


if __name__ == "__main__":
    main()
