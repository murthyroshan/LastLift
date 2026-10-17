"""M15 MS1: the eyes-free speech fallback (/v1/stt) transcribes through Whisper (mocked here), refuses empty or huge
bodies, and is capped per minute."""
import httpx
from fastapi.testclient import TestClient

from lastlift import main


def test_stt_transcribes_and_is_capped(monkeypatch):
    monkeypatch.setattr(main, "settings", type(main.settings)(**{**main.settings.__dict__, "groq_api_key": "k"}))
    sent = []

    def fake_post(url, **kw):
        sent.append((url, kw["data"]["model"]))
        return httpx.Response(200, json={"text": " Can I get to Wonderland step-free? "})
    monkeypatch.setattr(httpx, "post", fake_post)
    main._STT_CALLS.clear()
    with TestClient(main.app) as c:
        r = c.post("/v1/stt", content=b"fake-webm-bytes", headers={"Content-Type": "audio/webm"})
        assert r.status_code == 200 and r.json()["text"] == "Can I get to Wonderland step-free?"
        assert sent[0][1] == "whisper-large-v3-turbo"
        assert c.post("/v1/stt", content=b"").status_code == 400
        codes = [c.post("/v1/stt", content=b"x", headers={"Content-Type": "audio/webm"}).status_code for _ in range(25)]
        assert 429 in codes and codes.count(200) == main.STT_PER_MIN - 1
    main._STT_CALLS.clear()
