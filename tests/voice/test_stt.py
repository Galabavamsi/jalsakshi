"""voice/stt.py: Sarvam speech-to-text request shape, keyterms, errors and format sniffing."""

import json
from email.parser import BytesParser
from email.policy import HTTP

import httpx
import pytest

from jalsakshi.voice.stt import (
    DEFAULT_KEYTERMS,
    MAX_KEYTERM_CHARS,
    MAX_KEYTERMS,
    SARVAM_STT_URL,
    SttError,
    Transcript,
    normalize_keyterms,
    sniff_audio_format,
    transcribe,
)

KEY = "sk-test-not-real"
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 24
MP3_ID3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 4
MP3_FRAME = b"\xff\xfb\x90\x00" * 4
OGG = b"OggS\x00\x02" + b"\x00" * 20


def parse_multipart(request: httpx.Request) -> dict[str, tuple[str | None, str | None, bytes]]:
    """``{field: (filename, content_type, body)}`` for a multipart request."""
    content_type = request.headers["content-type"]
    raw = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + request.content
    message = BytesParser(policy=HTTP).parsebytes(raw)
    fields = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        body = part.get_payload(decode=True) or b""
        fields[name] = (part.get_filename(), part.get_content_type(), body)
    return fields


class FakeSarvam:
    """Answers like Sarvam STT and keeps the requests."""

    def __init__(self, reply: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.reply = reply

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if self.reply is not None:
            return self.reply
        return httpx.Response(
            200,
            json={
                "request_id": "req-1",
                "transcript": " नल  से पानी नहीं आया ",
                "language_code": "hi-IN",
            },
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def test_transcribe_sends_multipart_with_keyterms() -> None:
    sarvam = FakeSarvam()
    result = transcribe(MP3_ID3, "rec-1.wav", api_key=KEY, http=sarvam.client())

    assert result == Transcript(
        text="नल से पानी नहीं आया", language_code="hi-IN", request_id="req-1", model="saaras:v4"
    )
    (request,) = sarvam.requests
    assert request.method == "POST"
    assert str(request.url) == SARVAM_STT_URL
    assert request.headers["api-subscription-key"] == KEY
    fields = parse_multipart(request)
    assert fields["model"][2] == b"saaras:v4"
    assert fields["language_code"][2] == b"hi-IN"
    assert json.loads(fields["keyterms"][2].decode()) == list(DEFAULT_KEYTERMS)
    filename, content_type, body = fields["file"]
    assert filename == "rec-1.mp3"  # the bytes are MP3, whatever the name said
    assert content_type == "audio/mpeg"
    assert body == MP3_ID3


def test_keyterms_only_for_v4() -> None:
    sarvam = FakeSarvam()
    result = transcribe(WAV, "a.wav", api_key=KEY, http=sarvam.client(), model="saaras:v3")
    assert result.model == "saaras:v3"
    fields = parse_multipart(sarvam.requests[0])
    assert "keyterms" not in fields
    assert fields["file"][1] == "audio/wav"


def test_custom_keyterms_and_language() -> None:
    sarvam = FakeSarvam()
    transcribe(
        OGG,
        "x",
        api_key=KEY,
        http=sarvam.client(),
        language="unknown",
        keyterms=["टंकी", " टंकी ", "", "नल जल मित्र"],
    )
    fields = parse_multipart(sarvam.requests[0])
    assert fields["language_code"][2] == b"unknown"
    assert json.loads(fields["keyterms"][2].decode()) == ["टंकी", "नल जल मित्र"]
    assert fields["file"][0] == "x.ogg"


def test_normalize_keyterms_enforces_limits() -> None:
    too_long = "क" * (MAX_KEYTERM_CHARS + 1)
    many = [f"term{i}" for i in range(MAX_KEYTERMS + 10)]
    assert normalize_keyterms([too_long, "पानी", "पानी"]) == ["पानी"]
    assert normalize_keyterms(["क" * MAX_KEYTERM_CHARS]) == ["क" * MAX_KEYTERM_CHARS]
    assert normalize_keyterms(many) == many[:MAX_KEYTERMS]


def test_default_keyterms_fit_the_limits() -> None:
    assert normalize_keyterms(DEFAULT_KEYTERMS) == list(DEFAULT_KEYTERMS)


def test_http_error_raises_without_leaking_key() -> None:
    reply = httpx.Response(403, json={"error": {"message": "invalid api key"}})
    with pytest.raises(SttError, match="HTTP 403 invalid api key") as info:
        transcribe(WAV, "a.wav", api_key=KEY, http=FakeSarvam(reply).client())
    assert KEY not in str(info.value)


def test_transport_error_raises_stt_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(SttError, match="ConnectTimeout"):
        transcribe(
            WAV, "a.wav", api_key=KEY, http=httpx.Client(transport=httpx.MockTransport(boom))
        )


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(200, json={"request_id": "r", "transcript": "   ", "language_code": None}),
        httpx.Response(200, json={"request_id": "r"}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=["a list"]),
    ],
)
def test_empty_or_bad_reply_raises(reply: httpx.Response) -> None:
    with pytest.raises(SttError):
        transcribe(WAV, "a.wav", api_key=KEY, http=FakeSarvam(reply).client())


def test_empty_audio_is_not_sent() -> None:
    sarvam = FakeSarvam()
    with pytest.raises(SttError, match="no audio"):
        transcribe(b"", "a.wav", api_key=KEY, http=sarvam.client())
    assert sarvam.requests == []


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (WAV, "wav"),
        (MP3_ID3, "mp3"),
        (MP3_FRAME, "mp3"),
        (b"\xff\xf3\x64\xc4", "mp3"),  # MPEG-2 layer III
        (OGG, "ogg"),
        (b"\xff\xf1\x50\x80", "bin"),  # AAC ADTS: sync word but layer 0
        (b"\xff\xeb\x90\x00", "bin"),  # reserved MPEG version
        (b"RIFF\x00\x00\x00\x00AVI ", "bin"),
        (b"<html>", "bin"),
        (b"\xff", "bin"),
        (b"", "bin"),
    ],
)
def test_sniff_audio_format(data: bytes, expected: str) -> None:
    assert sniff_audio_format(data) == expected
