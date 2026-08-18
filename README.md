# Clinic-Caller-Bot

## What this project is

This places real phone calls and plays a patient. I ran about 10 full conversations against a clinic voice agent, then sat through the recordings and wrote up what broke. Each call gets an mp3 of both sides and a transcript. If something was actually wrong, it is recorded in “What I found” session at the bottom of this README.

## What I used

Python, FastAPI, Twilio Voice, Media Streams, OpenAI Realtime, ngrok, ffmpeg. FastAPI is only there because Twilio needs an HTTP webhook and a WebSocket. Each patient is a JSON file. Secrets go in .env. As there is only 10 calls，do not need Postgres. In the future, for scalability, we need to do database persistence like Postgres.

## How it works

I start the server and ngrok. A command tells Twilio to dial the clinic from my number. When they pick up, Twilio opens a Media Stream to my WebSocket. That handler connects to OpenAI Realtime, loads the patient JSON, and forwards audio both ways until someone hangs up. The patient waits for the clinic to speak first. After the call, the recording becomes an mp3 and I write the transcript next to it.

## Why I choose Realtime

The first thing anyone judging this will do is listen. The usual pipeline (STT, then GPT, then TTS) is cheaper, but two voice systems on a phone already add delay, and another three hops means the patient pauses after every sentence. ConversationRelay would have done STT/TTS for me; that's fine for a production agent, but here it would show up as dead air on the recording. So I used Realtime: audio in, audio out, one hop. The prompt is a persona and a goal, not a script. I write bugs after hangup, at the bottom of this README. Realtime's job is to talk.

## How to run this project

1. We need a Twilio number, an OpenAI key, ngrok, and ffmpeg.

2. Under the project root folder, copy ·.env.example· to ·.env· and fill in the keys. It looks like this:

TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_FROM_NUMBER=+15551234567
OPENAI_API_KEY=sk-your-openai-key
PUBLIC_HOST=something.ngrok-free.app

PUBLIC_HOST is the ngrok hostname from step 3, without https://. Start ngrok once if you need to see it, paste it here, then come back to step 2.

3. Install and start the server:

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

4. In another terminal, start the tunnel, then place a call:

ngrok http 8000
python -m bot run scenarios/schedule_checkup.json

## What I found

Nothing here yet. After I listen to the calls, I will list only the issues that actually matter: what happened, why it is a problem, and which recording and timestamp to play.
