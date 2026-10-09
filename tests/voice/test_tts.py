"""voice/tts.py: runtime Sarvam TTS, the S3 cache, text chunking and filling Play actions."""

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from botocore.exceptions import ClientError

from jalsakshi.voice.actions import GetDigits, Hangup, Play, Record
from jalsakshi.voice.catalog import PromptCatalog
from jalsakshi.voice.tts import (
    CACHE_CONTROL,
    DEFAULT_KEY_PREFIX,
    MAX_CHUNK_CHARS,
    SARVAM_TTS_URL,
    RuntimeTts,
    TtsError,
    dyn_key,
    fill_dynamic_audio,
    split_text,
)

ROOT = Path(__file__).resolve().parents[2]
KEY = "sk-test-not-real"
BUCKET = "prompts-bucket"
BASE = "https://cdn.example/prompts/hi"
FAKE_MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 8


class FakeS3:
    """Just enough of the boto3 S3 client: head_object and put_object on a dict."""

    def __init__(self, head_error: str = "404", put_error: str | None = None) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.heads: list[str] = []
        self.head_error = head_error
        self.put_error = put_error

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.heads.append(Key)
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": self.head_error, "Message": "x"}}, "HeadObject")
        return {"ContentLength": len(self.objects[(Bucket, Key)]["Body"])}

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.put_error:
            raise ClientError({"Error": {"Code": self.put_error, "Message": "x"}}, "PutObject")
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs
        return {}


class FakeSarvam:
    """Answers like Sarvam TTS and keeps the requests."""

    def __init__(self, reply: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.reply = reply

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.reply is not None:
            return self.reply
        audio = base64.b64encode(FAKE_MP3).decode()
        return httpx.Response(200, json={"request_id": "r", "audios": [audio]})

    @property
    def texts(self) -> list[str]:
        return [json.loads(r.content)["text"] for r in self.requests]

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def cat() -> PromptCatalog:
    return PromptCatalog.from_file(ROOT / "prompts" / "hi.yaml")


def make_tts(sarvam: FakeSarvam, s3: FakeS3, **kwargs: Any) -> RuntimeTts:
    return RuntimeTts(KEY, BUCKET, s3, sarvam.client(), BASE + "/", **kwargs)


def test_dyn_key_is_hash_of_voice_and_text() -> None:
    digest = hashlib.sha256("ritu|बारह घर".encode()).hexdigest()[:32]
    assert dyn_key("बारह घर") == f"dyn/{digest}.mp3"
    assert dyn_key("बारह घर", "anushka") != dyn_key("बारह घर")
    assert dyn_key("a") != dyn_key("b")


def test_ensure_renders_uploads_and_returns_cdn_url() -> None:
    sarvam, s3 = FakeSarvam(), FakeS3()
    url = make_tts(sarvam, s3).ensure("  बारह   घरों में पानी नहीं आया। ")

    key = dyn_key("बारह घरों में पानी नहीं आया।")
    assert url == f"{BASE}/{key}"
    (request,) = sarvam.requests
    assert str(request.url) == SARVAM_TTS_URL
    assert request.headers["api-subscription-key"] == KEY
    assert json.loads(request.content) == {
        "text": "बारह घरों में पानी नहीं आया।",
        "language_code": "hi-IN",
        "model": "bulbul:v3",
        "speaker": "ritu",
        "pace": 0.9,
        "speech_sample_rate": 8000,
        "output_audio_codec": "mp3",
    }
    stored = s3.objects[(BUCKET, f"{DEFAULT_KEY_PREFIX}/{key}")]
    assert stored["Body"] == FAKE_MP3
    assert stored["ContentType"] == "audio/mpeg"
    assert stored["CacheControl"] == CACHE_CONTROL == "public, max-age=31536000, immutable"


def test_s3_key_and_url_line_up_with_custom_prefix() -> None:
    sarvam, s3 = FakeSarvam(), FakeS3()
    tts = make_tts(sarvam, s3, key_prefix="/audio/x/")
    url = tts.ensure("नमस्ते")
    key = dyn_key("नमस्ते")
    assert url == f"{BASE}/{key}"
    assert (BUCKET, f"audio/x/{key}") in s3.objects


def test_cache_hit_skips_sarvam() -> None:
    sarvam, s3 = FakeSarvam(), FakeS3()
    key = f"{DEFAULT_KEY_PREFIX}/{dyn_key('नमस्ते')}"
    s3.objects[(BUCKET, key)] = {"Body": FAKE_MP3}

    assert make_tts(sarvam, s3).ensure("नमस्ते") == f"{BASE}/{dyn_key('नमस्ते')}"
    assert sarvam.requests == []
    assert s3.heads == [key]


def test_second_ensure_uses_memory_cache() -> None:
    sarvam, s3 = FakeSarvam(), FakeS3()
    tts = make_tts(sarvam, s3)
    first = tts.ensure("नमस्ते")
    assert tts.ensure("नमस्ते") == first
    assert len(sarvam.requests) == 1
    assert len(s3.heads) == 1


def test_head_access_denied_is_treated_as_miss() -> None:
    sarvam, s3 = FakeSarvam(), FakeS3(head_error="403")
    make_tts(sarvam, s3).ensure("नमस्ते")
    assert len(sarvam.requests) == 1


def test_sarvam_http_error_raises_tts_error_without_key() -> None:
    reply = httpx.Response(429, json={"error": {"message": "rate limited"}})
    s3 = FakeS3()
    with pytest.raises(TtsError, match="HTTP 429 rate limited") as info:
        make_tts(FakeSarvam(reply), s3).ensure("नमस्ते")
    assert KEY not in str(info.value)
    assert s3.objects == {}


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(200, json={"audios": []}),
        httpx.Response(200, json={"audios": ["!!not base64!!"]}),
        httpx.Response(200, json={"audios": [base64.b64encode(b"RIFF....WAVE").decode()]}),
        httpx.Response(200, text="oops"),
    ],
)
def test_bad_audio_raises(reply: httpx.Response) -> None:
    with pytest.raises(TtsError):
        make_tts(FakeSarvam(reply), FakeS3()).ensure("नमस्ते")


def test_transport_error_raises_tts_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    tts = RuntimeTts(KEY, BUCKET, FakeS3(), httpx.Client(transport=httpx.MockTransport(boom)), BASE)
    with pytest.raises(TtsError, match="ReadTimeout"):
        tts.ensure("नमस्ते")


def test_put_failure_raises_tts_error() -> None:
    with pytest.raises(TtsError, match="could not store"):
        make_tts(FakeSarvam(), FakeS3(put_error="AccessDenied")).ensure("नमस्ते")


def test_ensure_rejects_empty_and_long_text() -> None:
    tts = make_tts(FakeSarvam(), FakeS3())
    with pytest.raises(TtsError, match="no text"):
        tts.ensure("   ")
    with pytest.raises(TtsError, match="ensure_all"):
        tts.ensure("क" * (MAX_CHUNK_CHARS + 1))


def test_ensure_all_renders_each_chunk() -> None:
    sentence = "पानी की टंकी आज साफ की जाएगी। "
    text = sentence * 40
    sarvam, s3 = FakeSarvam(), FakeS3()
    urls = make_tts(sarvam, s3).ensure_all(text)
    chunks = split_text(text)
    assert len(urls) == len(chunks) > 1
    assert urls == [f"{BASE}/{dyn_key(c)}" for c in chunks]
    # identical chunks share one clip
    assert len(sarvam.requests) == len(set(chunks))


def test_split_text_on_sentences() -> None:
    text = ("नल से पानी नहीं आया। " * 30) + "क्या मोटर ठीक है?"
    chunks = split_text(text)
    assert all(len(c) <= MAX_CHUNK_CHARS for c in chunks)
    assert all(c.endswith(("।", "?")) for c in chunks)
    assert " ".join(chunks) == " ".join(text.split())


def test_split_text_edge_cases() -> None:
    assert split_text("") == []
    assert split_text(" \n ") == []
    assert split_text("छोटा  वाक्य") == ["छोटा वाक्य"]
    words = split_text("शब्द " * 200, limit=50)
    assert all(len(c) <= 50 for c in words)
    assert " ".join(words) == " ".join(("शब्द " * 200).split())
    assert split_text("x" * 120, limit=50) == ["x" * 50, "x" * 50, "x" * 20]
    with pytest.raises(ValueError):
        split_text("a", limit=0)


def test_fill_dynamic_audio_fills_only_missing_clips(cat: PromptCatalog) -> None:
    sarvam, s3 = FakeSarvam(), FakeS3()
    count = Play(prompt_key="operator.summary_no_supply", text_hi="बारह घरों में पानी नहीं आया")
    clip = Play(prompt_key="operator.greet", text_hi=cat.text("operator.greet"))
    given = Play(prompt_key="custom.x", text_hi="पहले से", audio_url="https://cdn.example/x.mp3")
    gather = GetDigits(prompts=[Play(prompt_key="wp.name", text_hi="खपरी टंकी"), clip])
    actions = [clip, count, given, gather, Record()]

    filled = fill_dynamic_audio(actions, make_tts(sarvam, s3), cat)

    assert filled[0] == clip  # pre-rendered: the adapter builds its URL
    assert filled[1].audio_url == f"{BASE}/{dyn_key(count.text_hi)}"
    assert filled[2] == given
    assert isinstance(filled[3], GetDigits)
    assert filled[3].prompts[0].audio_url == f"{BASE}/{dyn_key('खपरी टंकी')}"
    assert filled[3].prompts[1] == clip
    assert filled[4] == Record()
    assert sarvam.texts == [count.text_hi, "खपरी टंकी"]
    assert actions[1].audio_url is None  # input untouched


def test_fill_dynamic_audio_expands_long_text_in_place(cat: PromptCatalog) -> None:
    long_text = "सूचना: कल सुबह पानी नहीं आएगा। " * 25
    play = Play(prompt_key="broadcast.text", text_hi=long_text)
    gather = GetDigits(prompts=[play])
    filled = fill_dynamic_audio([play, gather], make_tts(FakeSarvam(), FakeS3()), cat)

    chunks = split_text(long_text)
    assert len(chunks) > 1
    top = filled[: len(chunks)]
    assert [p.text_hi for p in top] == chunks
    assert all(p.prompt_key == "broadcast.text" and p.audio_url for p in top)
    assert isinstance(filled[-1], GetDigits)
    assert [p.text_hi for p in filled[-1].prompts] == chunks
    assert len(filled) == len(chunks) + 1


def test_fill_dynamic_audio_without_tts_or_on_error_leaves_actions(
    cat: PromptCatalog, caplog: pytest.LogCaptureFixture
) -> None:
    actions = [Play(prompt_key="wp.name", text_hi="खपरी टंकी"), Hangup()]
    assert fill_dynamic_audio(actions, None, cat) == actions
    assert "no runtime TTS" in caplog.text

    caplog.clear()
    failing = make_tts(FakeSarvam(httpx.Response(500, text="down")), FakeS3())
    assert fill_dynamic_audio(actions, failing, cat) == actions
    assert "runtime TTS failed" in caplog.text
    assert KEY not in caplog.text
