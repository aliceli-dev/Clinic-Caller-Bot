from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "scenarios"


def load_patient(name: str) -> dict:
    path = SCENARIOS / f"{name}.json"
    with path.open() as f:
        return json.load(f)


def patient_script(patient: dict) -> str:
    wait = patient.get("wait_for_clinic", True)
    wait_line = (
        "Wait for the clinic to speak first. Do not greet until they have greeted you."
        if wait
        else "Start talking as soon as you hear anything, even if you talk over their greeting."
    )
    extras = patient.get("extras", "")
    return f"""
You are a real person calling a medical clinic, not an assistant and not a robot.
Your name is {patient["name"]}.
What you want: {patient["goal"]}.
Things you know: {patient.get("knows", "not much besides your name")}.
{wait_line}
Speak in short turns, like someone on a phone. Do not list options. Do not narrate what you are doing.
If they ask for a callback number, make one up that looks like a US mobile number.
Stay on the line until the goal is done or they clearly cannot help.
{extras}
""".strip()
