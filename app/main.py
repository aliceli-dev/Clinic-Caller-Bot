import asyncio
import json
import os

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, VoiceResponse

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "")
REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-mini-realtime-preview")

# Hardcoded for step 1. Step 3 will load this from a JSON scenario file.
PATIENT_INSTRUCTIONS = """
Currently you are a real person calling a medical clinic, not an assistant and not a robot.
Your name is Alice Li. You want to schedule a routine checkup.
Wait for the clinic to speak first. Do not greet until they have greeted you.
Speak in short turns, like someone on a phone. Do not list options. Do not narrate what you are doing.
If they ask for a day, prefer a weekday morning. If they ask for a callback number, make one up.
Stay on the line until the appointment is booked or they clearly cannot help.
""".strip()

app = FastAPI()


@app.get("/")
async def health():
    return {"ok": True}


@app.api_route("/twiml", methods=["GET", "POST"])
async def twiml(request: Request):
    """Twilio fetches this after the clinic picks up. We only tell it where to stream audio."""
    host = request.url.hostname or PUBLIC_HOST
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{host}/media-stream")
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """Twilio audio in one direction, OpenAI Realtime in the other. Same μ-law bytes both ways."""
    await websocket.accept()
    if not OPENAI_API_KEY:
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
                        "instructions": PATIENT_INSTRUCTIONS,
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcmu"},
                                "turn_detection": {"type": "server_vad"},
                            },
                            "output": {
                                "format": {"type": "audio/pcmu"},
                                "voice": "alloy",
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
                        print("stream started", stream_sid)
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
                        # Clinic started talking over the patient: stop playback.
                        await websocket.send_json(
                            {"event": "clear", "streamSid": stream_sid}
                        )
                    elif kind == "error":
                        print("openai error", event)
            except Exception as exc:
                print("openai socket error", exc)

        await asyncio.gather(from_twilio(), from_openai())
