import json
import shutil
import subprocess

import httpx
import pytest
import respx
import sentry_sdk
from sentry_sdk.transport import Transport

from app.config import settings
from app.media import MediaError, extract_audio
from app.models import GeminiModels
from app.observability import scrub


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
async def test_actual_ffmpeg_extracts_short_audio(tmp_path):
    video = tmp_path / "input.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(video)], check=True)
    audio, duration = await extract_audio(video)
    assert 0 < duration <= 2 and audio.stat().st_size > 0


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="FFprobe not installed")
async def test_fake_video_rejected(tmp_path):
    path = tmp_path / "notvideo.mp4"
    path.write_text("not a video")
    with pytest.raises(MediaError):
        await extract_audio(path)


@respx.mock
async def test_gemini_real_wire_contract(tmp_path):
    settings().gemini_api_key = "fake-test-key"
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"mock audio")
    output = {"transcript": [], "claims": [], "omitted_claims": 0, "language": "en", "usable_speech": False}
    route = respx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{settings().gemini_model}:generateContent").mock(
        return_value=httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": json.dumps(output)}]}}], "usageMetadata": {
                "promptTokenCount": 20, "candidatesTokenCount": 5, "totalTokenCount": 25,
            }}))
    envelopes = []

    class Capture(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    with sentry_sdk.init(dsn="https://public@sentry.example/1", transport=Capture(),
                         traces_sample_rate=1.0, before_send_transaction=scrub,
                         include_local_variables=False, default_integrations=False):
        with sentry_sdk.start_transaction(name="gemini-test", op="test"):
            result = await GeminiModels().analyze(audio)
        sentry_sdk.flush()
    assert result.usable_speech is False
    sent = json.loads(route.calls[0].request.content)
    assert sent["generationConfig"]["responseJsonSchema"]["type"] == "object"
    assert sent["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "audio/mpeg"
    assert "key=" not in str(route.calls[0].request.url)
    transactions = [item.payload.json for envelope in envelopes for item in envelope.items
                    if item.headers.get("type") == "transaction"]
    streamed_spans = [item.payload.json for envelope in envelopes for item in envelope.items
                      if item.headers.get("type") == "span"]
    ai_spans = [span for payload in streamed_spans for span in payload["items"]
                if span["attributes"]["sentry.op"]["value"] == "gen_ai.request"]
    assert ai_spans, [(item.headers, item.payload.json) for envelope in envelopes for item in envelope.items]
    ai_span = ai_spans[0]
    attributes = ai_span["attributes"]
    assert attributes["gen_ai.operation.name"]["value"] == "transcribe_and_extract_claims"
    assert attributes["gen_ai.request.model"]["value"] == settings().gemini_model
    assert attributes["gen_ai.usage.input_tokens"]["value"] == 20
    serialized = json.dumps([transactions, streamed_spans])
    assert "mock audio" not in serialized
    assert "Transcribe this short audio" not in serialized


def test_sentry_scrubs_payloads():
    event = {"request": {"data": "secret"}, "user": {"ip": "1.2.3.4"}, "extra": {"transcript": "secret"},
             "breadcrumbs": {"values": ["secret"]}, "exception": {"values": [{"type": "ValueError", "value": "secret",
                "stacktrace": {"frames": [{"vars": {"api_key": "secret"}}]}}]},
             "spans": [{"op": "http.client", "description": "https://url?key=secret", "data": {"body": "secret"}}]}
    assert "secret" not in json.dumps(scrub(event, {}))
