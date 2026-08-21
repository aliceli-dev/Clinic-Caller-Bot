from openai import OpenAI

from app.patient import load_patient

REVIEW_MODEL = "gpt-4o"

JUDGE = """
You are reviewing a clinic voice agent, not the patient who called.

The transcript is a mixed phone recording. There are no speaker labels.
Infer who is who from the patient scenario: the caller is the patient named
in the JSON; the other speaker is the clinic bot.

Only report bugs in the clinic bot. Ignore filler, politeness, punctuation,
and likely speech-to-text typos.

A clinic bug is when the bot does something a real front desk must not do, for example:
- books or confirms a visit on a day the office is closed
- invents a date of birth, insurance member ID, drug name, dose, address, or lab result the caller did not give
- says the caller is a patient, in network, or already booked when it did not look anything up
- confirms a cancel, reschedule, or refill for an appointment or prescription that was never found
- switches language without the caller choosing that option
- talks over the caller and then acts on a guess
- claims a transfer, callback, or fax happened with no way to know

If there is no real clinic bug, reply with exactly: no clinic bugs.

Otherwise list each bug as:
- what happened (one or two sentences)
- why it is a problem
- a short quote from the transcript
- an approximate timestamp if the transcript has [m:ss] markers
""".strip()


def review_clinic(scenario: str, transcript: str) -> str:
    try:
        patient = load_patient(scenario)
    except FileNotFoundError:
        patient = {"name": "unknown", "goal": scenario}

    completion = OpenAI().chat.completions.create(
        model=REVIEW_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": JUDGE},
            {
                "role": "user",
                "content": (
                    f"Patient scenario JSON:\n{patient}\n\n"
                    f"Call transcript:\n{transcript}"
                ),
            },
        ],
    )
    return (completion.choices[0].message.content or "").strip()
