import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import requests
import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from openai import OpenAI
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.patient import load_patient, patient_script

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "")
REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-mini")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS = ROOT / "recordings"
TRANSCRIPTS = ROOT / "transcripts"

app = FastAPI()
openai_text = OpenAI()


@app.get("/")
async def health():
    return {"ok": True}


@app.api_route("/twiml", methods=["GET", "POST"])
async def twiml(request: Request):
    # Twilio asks what to do after pickup. We point it at the audio socket
    # and pass the patient file name in the query string.
    host = request.url.hostname or PUBLIC_HOST
    scenario = request.query_params.get("scenario", "schedule_checkup")
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{host}/media-stream?scenario={scenario}")
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    if not OPENAI_API_KEY:
        await websocket.close()
        return

    scenario = websocket.query_params.get("scenario", "schedule_checkup")
    try:
        script = patient_script(load_patient(scenario))
    except FileNotFoundError:
        print("unknown scenario", scenario)
        await websocket.close()
        return

    openai_url = f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}"
    async with websockets.connect(
        openai_url,
        additional_headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
    ) as openai_ws:
        await openai_ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "model": REALTIME_MODEL,
                        "output_modalities": ["audio"],
                        "instructions": script,
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcmu"},
                                "turn_detection": {"type": "server_vad"},
                            },
                            "output": {
                                "format": {"type": "audio/pcmu"},
                                "voice": "coral",
                            },
                        },
                    },
                }
            )
        )

        stream_sid = None

        async def from_twilio():
            nonlocal stream_sid
            try:
                async for raw in websocket.iter_text():
                    data = json.loads(raw)
                    event = data.get("event")
                    if event == "start":
                        stream_sid = data["start"]["streamSid"]
                        print("stream started", stream_sid, "scenario", scenario)
                    elif event == "media":
                        await openai_ws.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": data["media"]["payload"],
                                }
                            )
                        )
                    elif event == "stop":
                        break
            except WebSocketDisconnect:
                print("twilio disconnected")

        async def from_openai():
            try:
                async for raw in openai_ws:
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind == "response.output_audio.delta" and stream_sid:
                        await websocket.send_json(
                            {
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": event["delta"]},
                            }
                        )
                    elif kind == "input_audio_buffer.speech_started" and stream_sid:
                        await websocket.send_json(
                            {"event": "clear", "streamSid": stream_sid}
                        )
                    elif kind == "error":
                        print("openai error", event)
            except Exception as exc:
                print("openai socket error", exc)

        await asyncio.gather(from_twilio(), from_openai())


@app.post("/recording")
async def recording(request: Request):
    # Twilio posts here when the recording is ready. We save mp3 and a transcript.
    form = await request.form()
    recording_url = form.get("RecordingUrl")
    call_sid = form.get("CallSid") or "unknown"
    scenario = request.query_params.get("scenario", "call")
    if not recording_url:
        return {"ok": False}

    RECORDINGS.mkdir(exist_ok=True)
    TRANSCRIPTS.mkdir(exist_ok=True)

    mp3_url = f"{recording_url}.mp3"
    audio = requests.get(
        mp3_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=60
    )
    audio.raise_for_status()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}-{scenario}-{call_sid}"
    mp3_path = RECORDINGS / f"{base}.mp3"
    mp3_path.write_bytes(audio.content)
    print("saved", mp3_path)

    with mp3_path.open("rb") as f:
        text = openai_text.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="text",
        )
    txt_path = TRANSCRIPTS / f"{base}.txt"
    txt_path.write_text(text if isinstance(text, str) else str(text), encoding="utf-8")
    print("saved", txt_path)
    return {"ok": True}
