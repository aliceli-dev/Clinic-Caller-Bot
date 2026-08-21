from pathlib import Path
import os
import sys

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

CLINIC_NUMBER = "+18054398008"
ROOT = Path(__file__).resolve().parent.parent


def load_client():
    host = os.getenv("PUBLIC_HOST", "").strip()
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()
    if not host or not sid or not token or not from_number:
        print("fill TWILIO_* and PUBLIC_HOST in .env first")
        sys.exit(1)
    return Client(sid, token), host, from_number


def scenario_name(path_arg: str) -> str:
    scenario_path = Path(path_arg)
    if not scenario_path.is_absolute():
        scenario_path = ROOT / scenario_path
    if not scenario_path.exists():
        print("cannot find", scenario_path)
        sys.exit(1)
    return scenario_path.stem


def place_call(client, host, from_number, name):
    twiml_url = f"https://{host}/twiml?scenario={name}"
    recording_url = f"https://{host}/recording?scenario={name}"
    call = client.calls.create(
        to=CLINIC_NUMBER,
        from_=from_number,
        url=twiml_url,
        method="POST",
        record=True,
        recording_channels="mono",
        recording_status_callback=recording_url,
        recording_status_callback_method="POST",
        recording_status_callback_event=["completed"],
    )
    print("calling", CLINIC_NUMBER, "as", name)
    print("call sid", call.sid)
    return call


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "run":
        print("usage: python -m bot run scenarios/schedule_checkup.json")
        sys.exit(1)

    client, host, from_number = load_client()
    name = scenario_name(sys.argv[2])
    place_call(client, host, from_number, name)


if __name__ == "__main__":
    main()
