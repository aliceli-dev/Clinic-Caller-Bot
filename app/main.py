import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import requests
import websockets
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from openai import OpenAI
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.patient import load_patient, patient_script
from app.review import review_clinic

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "")
REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-mini")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS = ROOT / "recordings"
TRANSCRIPTS = ROOT / "transcripts"
REVIEWS = ROOT / "reviews"

app = FastAPI()
openai_text = OpenAI()


@app.get("/")
async def health():
    return {"ok": True}


def realtime_session(script: str) -> dict:
    return {
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


@app.api_route("/twiml", methods=["GET", "POST"])
async def twiml(request: Request):
    # Twilio asks what to do after pickup. We point it at the audio socket
    # and pass the patient file name as a Stream Parameter. Query strings on
    # the wss URL get dropped; customParameters on the start event do not.
    host = request.url.hostname or PUBLIC_HOST
    scenario = request.query_params.get("scenario", "schedule_checkup")
    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=f"wss://{host}/media-stream")
    stream.parameter(name="scenario", value=scenario)
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    if not OPENAI_API_KEY:
        await websocket.close()
        return

    incoming = asyncio.Queue()

    async def pump_twilio():
        try:
            async for raw in websocket.iter_text():
                await incoming.put(json.loads(raw))
        except WebSocketDisconnect:
            print("twilio disconnected")
        finally:
            await incoming.put(None)

    async def send_audio(openai_ws, payload):
        await openai_ws.send(
            json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "audio": payload,
                }
            )
        )

    pump = asyncio.create_task(pump_twilio())
    stream_sid = None
    scenario = "schedule_checkup"
    script = None
    buffered = []
    try:
        # Handle Twilio start before talking to OpenAI, so a slow
        # Realtime connect cannot swallow the scenario Parameter.
        while True:
            data = await incoming.get()
            if data is None:
                return
            event = data.get("event")
            if event == "start":
                stream_sid = data["start"]["streamSid"]
                params = data["start"].get("customParameters") or {}
                scenario = (
                    params.get("scenario")
                    or websocket.query_params.get("scenario")
                    or "schedule_checkup"
                )
                print("stream started", stream_sid, "scenario", scenario, "params", params)
                try:
                    script = patient_script(load_patient(scenario))
                except FileNotFoundError:
                    print("unknown scenario", scenario)
                    await websocket.close()
                    return
                break
            elif event == "media":
                buffered.append(data["media"]["payload"])
            elif event == "stop":
                return

        openai_url = f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}"
        async with websockets.connect(
            openai_url,
            additional_headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            open_timeout=20,
        ) as openai_ws:
            print("openai realtime connected", scenario)
            await openai_ws.send(json.dumps(realtime_session(script)))
            for payload in buffered:
                await send_audio(openai_ws, payload)
            buffered.clear()

            async def from_twilio():
                try:
                    while True:
                        data = await incoming.get()
                        if data is None:
                            break
                        event = data.get("event")
                        if event == "media":
                            await send_audio(openai_ws, data["media"]["payload"])
                        elif event == "stop":
                            break
                except Exception as exc:
                    print("twilio loop error", exc)
                finally:
                    await openai_ws.close()

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
                except websockets.ConnectionClosed:
                    print("openai socket closed")
                except Exception as exc:
                    print("openai socket error", exc)

            await asyncio.gather(from_twilio(), from_openai())
    finally:
        pump.cancel()
        try:
            await pump
        except asyncio.CancelledError:
            pass


def save_transcript_and_review(mp3_path: Path, base: str, scenario: str) -> None:
    # Whisper first (cheap, we need the txt anyway), then a text model
    # reads the call for clinic-bot bugs. Do this after Twilio already got 200.
    TRANSCRIPTS.mkdir(exist_ok=True)
    REVIEWS.mkdir(exist_ok=True)

    with mp3_path.open("rb") as f:
        result = openai_text.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
        )
    text = result.text if hasattr(result, "text") else str(result)
    txt_path = TRANSCRIPTS / f"{base}.txt"
    txt_path.write_text(text, encoding="utf-8")
    print("saved", txt_path)

    timed_lines = []
    for segment in getattr(result, "segments", None) or []:
        start = int(getattr(segment, "start", 0) or 0)
        timed_lines.append(
            f"[{start // 60}:{start % 60:02d}] {getattr(segment, 'text', '').strip()}"
        )
    timed = "\n".join(timed_lines) if timed_lines else text

    review = review_clinic(scenario, timed)
    review_path = REVIEWS / f"{base}.txt"
    review_path.write_text(review, encoding="utf-8")
    print("saved", review_path)


@app.post("/recording")
async def recording(request: Request, background_tasks: BackgroundTasks):
    # Twilio posts here when the recording is ready. We save mp3 and a transcript.
    form = await request.form()
    recording_url = form.get("RecordingUrl")
    call_sid = form.get("CallSid") or "unknown"
    scenario = request.query_params.get("scenario", "call")
    if not recording_url:
        return {"ok": False}

    RECORDINGS.mkdir(exist_ok=True)

    # RequestedChannels=1 downmixes Twilio's dual-channel default to one track.
    mp3_url = f"{recording_url}.mp3?RequestedChannels=1"
    audio = requests.get(
        mp3_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=60
    )
    audio.raise_for_status()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}-{scenario}-{call_sid}"
    mp3_path = RECORDINGS / f"{base}.mp3"
    mp3_path.write_bytes(audio.content)
    print("saved", mp3_path)

    background_tasks.add_task(save_transcript_and_review, mp3_path, base, scenario)
    return {"ok": True}
