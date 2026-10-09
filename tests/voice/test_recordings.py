"""voice/recordings.py: fetching Vobiz recordings safely, archiving them, deleting the copy."""

from typing import Any

import httpx
import pytest
from botocore.exceptions import ClientError

from jalsakshi.voice.adapters.vobiz import API_BASE, VobizAuth
from jalsakshi.voice.recordings import (
    RecordingError,
    archive_recording,
    delete_vobiz_recording,
    fetch_recording,
    is_vobiz_url,
)

AUTH = VobizAuth(auth_id="MA_TEST", auth_token="secret-token")
REC_URL = "https://media.vobiz.ai/v1/Account/MA_TEST/Recording/rec-1.mp3"
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 8
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 24


class Recorder:
    """MockTransport handler that answers from a {url: response} map and keeps requests."""

    def __init__(self, routes: dict[str, httpx.Response]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.routes.get(str(request.url), httpx.Response(404))

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


class FakeS3:
    def __init__(self, error: str | None = None) -> None:
        self.puts: list[dict[str, Any]] = []
        self.error = error

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.error:
            raise ClientError({"Error": {"Code": self.error, "Message": "x"}}, "PutObject")
        self.puts.append(kwargs)
        return {}


# --- fetch_recording --------------------------------------------------------------------------


def test_fetch_sends_vobiz_auth_headers() -> None:
    server = Recorder({REC_URL: httpx.Response(200, content=MP3)})
    assert fetch_recording(REC_URL, AUTH, server.client()) == MP3
    (request,) = server.requests
    assert request.method == "GET"
    assert request.headers["X-Auth-ID"] == "MA_TEST"
    assert request.headers["X-Auth-Token"] == "secret-token"


@pytest.mark.parametrize(
    "url",
    [
        "http://media.vobiz.ai/rec.mp3",  # not https
        "https://vobiz.ai.evil.com/rec.mp3",
        "https://evilvobiz.ai/rec.mp3",
        "https://vobiz.ai/rec.mp3",  # apex is not a *.vobiz.ai host
        "https://169.254.169.254/latest/meta-data",
        "https://media.vobiz.ai@evil.com/rec.mp3",
        "https://user:pw@media.vobiz.ai/rec.mp3",
        "https://media.vobiz.ai:8443/rec.mp3",
        "file:///etc/passwd",
        "not a url",
        "",
    ],
)
def test_ssrf_guard_rejects_other_urls(url: str) -> None:
    server = Recorder({})
    assert not is_vobiz_url(url)
    with pytest.raises(RecordingError, match="refusing"):
        fetch_recording(url, AUTH, server.client())
    assert server.requests == []


def test_accepts_vobiz_subdomains() -> None:
    assert is_vobiz_url("https://api.vobiz.ai/api/v1/x")
    assert is_vobiz_url("https://MEDIA.Vobiz.AI:443/rec.mp3")


def test_redirect_within_vobiz_keeps_auth() -> None:
    target = "https://cdn.vobiz.ai/rec-1.mp3"
    server = Recorder(
        {
            REC_URL: httpx.Response(302, headers={"Location": target}),
            target: httpx.Response(200, content=MP3),
        }
    )
    assert fetch_recording(REC_URL, AUTH, server.client()) == MP3
    assert [str(r.url) for r in server.requests] == [REC_URL, target]
    assert server.requests[1].headers["X-Auth-Token"] == "secret-token"


def test_redirect_to_storage_drops_auth_headers() -> None:
    target = "https://bucket.s3.ap-south-1.amazonaws.com/rec-1.mp3?X-Amz-Signature=abc"
    server = Recorder(
        {
            REC_URL: httpx.Response(307, headers={"Location": target}),
            target: httpx.Response(200, content=MP3),
        }
    )
    assert fetch_recording(REC_URL, AUTH, server.client()) == MP3
    hop = server.requests[1]
    assert "X-Auth-Token" not in hop.headers
    assert "X-Auth-ID" not in hop.headers


@pytest.mark.parametrize(
    "location",
    ["http://cdn.vobiz.ai/rec.mp3", "https://10.0.0.5/rec.mp3", "https://localhost/rec.mp3"],
)
def test_unsafe_redirect_is_refused(location: str) -> None:
    server = Recorder({REC_URL: httpx.Response(302, headers={"Location": location})})
    with pytest.raises(RecordingError, match="refusing a redirect"):
        fetch_recording(REC_URL, AUTH, server.client())
    assert len(server.requests) == 1


def test_redirect_loop_is_bounded() -> None:
    server = Recorder({REC_URL: httpx.Response(302, headers={"Location": REC_URL})})
    with pytest.raises(RecordingError, match="too many redirects"):
        fetch_recording(REC_URL, AUTH, server.client())


def test_size_cap_by_header_and_by_body() -> None:
    declared = Recorder(
        {REC_URL: httpx.Response(200, content=MP3, headers={"Content-Length": "999999999"})}
    )
    with pytest.raises(RecordingError, match="limit"):
        fetch_recording(REC_URL, AUTH, declared.client(), max_bytes=1000)

    def chunks() -> Any:
        for _ in range(10):
            yield b"\x00" * 400

    streamed = Recorder({REC_URL: httpx.Response(200, content=chunks())})
    with pytest.raises(RecordingError, match="larger than 1000"):
        fetch_recording(REC_URL, AUTH, streamed.client(), max_bytes=1000)


def test_http_errors_and_empty_body() -> None:
    with pytest.raises(RecordingError, match="HTTP 401") as info:
        fetch_recording(REC_URL, AUTH, Recorder({REC_URL: httpx.Response(401)}).client())
    assert "secret-token" not in str(info.value)
    with pytest.raises(RecordingError, match="empty"):
        fetch_recording(REC_URL, AUTH, Recorder({REC_URL: httpx.Response(200)}).client())


def test_error_message_hides_query_string() -> None:
    url = REC_URL + "?token=signed-secret"
    with pytest.raises(RecordingError) as info:
        fetch_recording(url, AUTH, Recorder({}).client())
    assert "signed-secret" not in str(info.value)


def test_transport_error_maps_to_recording_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(RecordingError, match="ConnectError"):
        fetch_recording(REC_URL, AUTH, httpx.Client(transport=httpx.MockTransport(boom)))


# --- archive_recording ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "ext", "content_type"),
    [
        (MP3, "mp3", "audio/mpeg"),
        (WAV, "wav", "audio/wav"),
        (b"junk", "bin", "application/octet-stream"),
    ],
)
def test_archive_uses_sniffed_format_and_sse(data: bytes, ext: str, content_type: str) -> None:
    s3 = FakeS3()
    key = archive_recording(data, s3=s3, bucket="evidence", village_id="v-1", call_id="call-9")
    assert key == f"audio/v-1/call-9.{ext}"
    (put,) = s3.puts
    assert put["Bucket"] == "evidence"
    assert put["Key"] == key
    assert put["Body"] == data
    assert put["ServerSideEncryption"] == "AES256"
    assert put["ContentType"] == content_type


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "..", ".hidden", "a b"])
def test_archive_rejects_unsafe_key_parts(bad: str) -> None:
    with pytest.raises(ValueError):
        archive_recording(MP3, s3=FakeS3(), bucket="b", village_id=bad, call_id="c")
    with pytest.raises(ValueError):
        archive_recording(MP3, s3=FakeS3(), bucket="b", village_id="v", call_id=bad)


def test_archive_errors() -> None:
    with pytest.raises(RecordingError, match="no recording"):
        archive_recording(b"", s3=FakeS3(), bucket="b", village_id="v", call_id="c")
    with pytest.raises(RecordingError, match="could not archive"):
        archive_recording(MP3, s3=FakeS3("AccessDenied"), bucket="b", village_id="v", call_id="c")


# --- delete_vobiz_recording -------------------------------------------------------------------

DELETE_URL = f"{API_BASE}/Account/MA_TEST/Recording/rec-1/"


@pytest.mark.parametrize(("status", "deleted"), [(204, True), (200, True), (404, True)])
def test_delete_gone_statuses(status: int, deleted: bool) -> None:
    server = Recorder({DELETE_URL: httpx.Response(status)})
    assert delete_vobiz_recording("rec-1", AUTH, server.client()) is deleted
    (request,) = server.requests
    assert request.method == "DELETE"
    assert str(request.url) == DELETE_URL
    assert request.headers["X-Auth-ID"] == "MA_TEST"
    assert request.headers["X-Auth-Token"] == "secret-token"


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_delete_failure_returns_false(status: int, caplog: pytest.LogCaptureFixture) -> None:
    server = Recorder({DELETE_URL: httpx.Response(status)})
    assert delete_vobiz_recording("rec-1", AUTH, server.client()) is False
    assert str(status) in caplog.text
    assert "secret-token" not in caplog.text


def test_delete_never_raises() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = httpx.Client(transport=httpx.MockTransport(boom))
    assert delete_vobiz_recording("rec-1", AUTH, client) is False
    server = Recorder({})
    assert delete_vobiz_recording("../Call", AUTH, server.client()) is False
    assert server.requests == []
