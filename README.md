# Clinic-Caller-Bot

## What this project is

This places real phone calls and plays a patient. I ran about 10 full conversations against a clinic voice agent, then sat through the recordings and wrote up what broke. Each call gets an mp3 of both sides and a transcript. If something was actually wrong, it is recorded in “What I found” session at the bottom of this README.

## What I used

Python, FastAPI, Twilio Voice, Media Streams, OpenAI Realtime, ngrok, ffmpeg. FastAPI is only there because Twilio needs an HTTP webhook and a WebSocket. Each patient is a JSON file. Secrets go in .env. As there is only 10 calls，do not need Postgres. In the future, for scalability, we need to do database persistence like Postgres.

## How it works

I start the server and ngrok. A command tells Twilio to dial the clinic from my number. When they pick up, Twilio opens a Media Stream to my WebSocket. That handler connects to OpenAI Realtime, loads the patient JSON, and forwards audio both ways until someone hangs up. The patient waits for the clinic to speak first. After the call, the recording becomes an mp3 and I write the transcript next to it.

```mermaid
flowchart LR
  clinic[Clinic bot] <-->|phone| twilio[Twilio]
  twilio <-->|audio| code[My code]
  code <-->|audio| realtime[OpenAI Realtime]
```

## Why I choose Realtime

The first thing anyone judging this will do is listen. The usual pipeline (STT, then GPT, then TTS) is cheaper, but two voice systems on a phone already add delay, and another three hops means the patient pauses after every sentence. ConversationRelay would have done STT/TTS for me; that's fine for a production agent, but here it would show up as dead air on the recording. So I used Realtime: audio in, audio out, one hop. The prompt is a persona and a goal, not a script. I write bugs after hangup, at the bottom of this README. Realtime's job is to talk.

## How to run this project

You need a Twilio number, an OpenAI key, ngrok, and ffmpeg. Copy .env.example to .env and fill in the keys. PUBLIC_HOST is the ngrok hostname, without https://:

- TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
- TWILIO_AUTH_TOKEN=your_twilio_auth_token
- TWILIO_FROM_NUMBER=+15551234567
- OPENAI_API_KEY=sk-your-openai-key
- PUBLIC_HOST=xxx-xxx-discard.ngrok-free.dev

Open three terminals. In each one, go to the project folder.

1. Start the server.

source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000

2. Start ngrok so Twilio can reach your laptop. Leave this window open.

ngrok http 8000 --url https://majorette-parsnip-discard.ngrok-free.dev

3. Place a call. This is the step that actually dials.

source .venv/bin/activate
python -m bot run scenarios/<in scenarios folder>.json

To try a different patient, swap the json file, for example scenarios/refill.json.

Keep the first two terminals running. If you close them, the call dies.

## What I found

The bug I found is： The clinic agent keeps promising a live transfer that does not exist.

I hit this on 4 different calls: cancel, refill, reschedule, and a lab lookup for someone who was not in the system. Each time the agent got stuck, said it would connect me to patient support, and asked me to stay on the line. Then a different voice came on: “Hello. You've reached the Pretty Good AI test line. Goodbye.” After that the call was over. Nothing got cancelled, refilled, moved, or looked up.

Once I would have called it a flaky demo. Four times, same script, I think the agent is lying about the transfer. A front desk cannot tell a patient they are being handed off and then drop them on a goodbye line.

Play these. The handoff is near the end of each one.

- [`recordings/20260820-163516-cancel-CA3fb91557d2e46cdd2355602b5d69b6e8.mp3`](recordings/20260820-163516-cancel-CA3fb91557d2e46cdd2355602b5d69b6e8.mp3) around **0:49**. I asked to cancel something next week. They took a date of birth, said they could not finish the cancel, then “Transferring you now.” Test line at about **0:52**. Transcript: `transcripts/20260820-163516-cancel-CA3fb91557d2e46cdd2355602b5d69b6e8.txt`
- [`recordings/20260820-164413-refill-CAcbfb17556906c3a69f8e41b0534d4f19.mp3`](recordings/20260820-164413-refill-CAcbfb17556906c3a69f8e41b0534d4f19.mp3) around **1:09**. Blood pressure refill, they could not find a med on the chart, offered support, same transfer, same goodbye.
- [`recordings/20260820-164737-reschedule-CAabbc7d721cc10225e9dc628abb65e969.mp3`](recordings/20260820-164737-reschedule-CAabbc7d721cc10225e9dc628abb65e969.mp3) around **2:32**. Longer call. They never found the Thursday appointment, offered the support team, transferred at **2:32**, test line by **2:39**.
- [`recordings/20260820-170427-wrong_clinic-CAda5092d76bf71084aa84e7d66643eb63.mp3`](recordings/20260820-170427-wrong_clinic-CAda5092d76bf71084aa84e7d66643eb63.mp3) around **1:37**. Jordan Hale, lab result, they correctly said there was no record, then transferred anyway. Same test line at **1:44**.

The other 6 calls did not do this. 
