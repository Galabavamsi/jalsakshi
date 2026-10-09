"""prompts/render.py: planning, Sarvam request, caching, S3 upload and the CLI (offline)."""

import base64
import importlib.util
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import boto3
import httpx
import pytest
from moto import mock_aws

from jalsakshi.voice.catalog import PromptCatalog

ROOT = Path(__file__).resolve().parents[2]
FAKE_MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 8
REGION = "ap-south-1"


def _load_render() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "jalsakshi_prompt_render", ROOT / "prompts/render.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


render = _load_render()


@pytest.fixture
def cat() -> PromptCatalog:
    return PromptCatalog.from_file(ROOT / "prompts" / "hi.yaml")


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("JALSAKSHI_REGION", REGION)


@pytest.fixture
def aws(isolated_env: None) -> Iterator[None]:
    with mock_aws():
        yield


class FakeSarvam:
    """httpx transport that answers like Sarvam TTS and records requests."""

    def __init__(self, replies: list[httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.replies = replies or []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.replies:
            return self.replies.pop(0)
        return ok_reply()

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def ok_reply(audio: bytes = FAKE_MP3) -> httpx.Response:
    return httpx.Response(
        200, json={"request_id": "r-1", "audios": [base64.b64encode(audio).decode()]}
    )


def no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected HTTP call to {request.url}")


def client_for(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_voice_payload_matches_sarvam_contract() -> None:
    voice = render.Voice()
    body = voice.payload("Namaste", "hi-IN")
    assert body == {
        "text": "Namaste",
        "language_code": "hi-IN",
        "model": "bulbul:v3",
        "speaker": "ritu",
        "pace": 0.9,
        "speech_sample_rate": 8000,
        "output_audio_codec": "mp3",
    }
    assert render.Voice(temperature=0.3).payload("x", "hi-IN")["temperature"] == 0.3


def test_plan_covers_every_clip(cat: PromptCatalog, tmp_path: Path) -> None:
    jobs = render.plan(cat, tmp_path, render.Voice(), {})
    assert [job.key for job in jobs] == cat.audio_keys()
    plain = [k for k in cat.template_keys() if not cat.placeholders(k)]
    numbered = [k for k in cat.template_keys() if len(cat.placeholders(k)) == 1]
    assert len(jobs) == len(plain) + 9 * len(numbered)
    assert all(job.stale for job in jobs)
    variant = next(job for job in jobs if job.key == "operator.summary_no_supply.n3")
    assert variant.path == tmp_path / "operator.summary_no_supply.n3.mp3"
    assert "sankhya: teen" in variant.text


def test_plan_only_and_unknown(cat: PromptCatalog, tmp_path: Path) -> None:
    jobs = render.plan(cat, tmp_path, render.Voice(), {}, only=["household.bye"])
    assert [job.key for job in jobs] == ["household.bye"]
    with pytest.raises(render.RenderError, match="unknown"):
        render.plan(cat, tmp_path, render.Voice(), {}, only=["operator.summary_no_supply"])


def test_render_writes_clips_and_manifest(cat: PromptCatalog, tmp_path: Path) -> None:
    sarvam = FakeSarvam()
    jobs = render.plan(cat, tmp_path, render.Voice(), {}, only=["household.greet", "verify.bye"])
    manifest: dict[str, str] = {}
    with httpx.Client(transport=sarvam.transport()) as client:
        result = render.render(jobs, client, "key-123", render.Voice(), "hi-IN", tmp_path, manifest)
    assert result.rendered == ["household.greet", "verify.bye"]
    assert (tmp_path / "household.greet.mp3").read_bytes() == FAKE_MP3
    assert render.load_manifest(tmp_path) == manifest
    assert set(manifest) == {"household.greet", "verify.bye"}
    request = sarvam.requests[0]
    assert str(request.url) == "https://api.sarvam.ai/text-to-speech"
    assert request.headers["api-subscription-key"] == "key-123"
    assert sarvam.bodies[0]["text"] == cat.text("household.greet")
    assert sarvam.bodies[0]["language_code"] == "hi-IN"


def test_unchanged_clips_are_cached(cat: PromptCatalog, tmp_path: Path) -> None:
    voice = render.Voice()
    only = ["household.greet"]
    jobs = render.plan(cat, tmp_path, voice, {}, only=only)
    manifest: dict[str, str] = {}
    with client_for(FakeSarvam()) as client:
        render.render(jobs, client, "k", voice, "hi-IN", tmp_path, manifest)
    again = render.plan(cat, tmp_path, voice, render.load_manifest(tmp_path), only=only)
    assert not again[0].stale
    with client_for(no_network) as client:
        result = render.render(again, client, "k", voice, "hi-IN", tmp_path, manifest)
    assert result.skipped == ["household.greet"] and not result.rendered
    forced = render.plan(cat, tmp_path, voice, manifest, only=only, force=True)
    assert forced[0].stale
    slower = render.plan(cat, tmp_path, render.Voice(pace=0.8), manifest, only=only)
    assert slower[0].stale
    changed = PromptCatalog({"version": 1, "language": "hi-IN", "household": {"greet": "Ram Ram"}})
    assert render.plan(changed, tmp_path, voice, manifest, only=only)[0].stale


def test_synthesize_retries_rate_limits() -> None:
    sarvam = FakeSarvam([httpx.Response(429, json={"error": {"message": "slow down"}}), ok_reply()])
    waits: list[float] = []
    with httpx.Client(transport=sarvam.transport()) as client:
        audio = render.synthesize(client, "k", {"text": "x"}, sleep=waits.append)
    assert audio == FAKE_MP3
    assert waits == [2.0]
    assert len(sarvam.requests) == 2


def test_synthesize_gives_up_after_attempts() -> None:
    replies = [httpx.Response(503, text="busy") for _ in range(3)]
    with (
        httpx.Client(transport=FakeSarvam(replies).transport()) as client,
        pytest.raises(render.RenderError, match="HTTP 503"),
    ):
        render.synthesize(client, "k", {"text": "x"}, sleep=lambda _: None)


def test_synthesize_reports_client_errors() -> None:
    reply = httpx.Response(
        403, json={"error": {"message": "invalid key", "code": "invalid_api_key_error"}}
    )
    with (
        httpx.Client(transport=FakeSarvam([reply]).transport()) as client,
        pytest.raises(render.RenderError, match="403 invalid key"),
    ):
        render.synthesize(client, "bad", {"text": "x"})


@pytest.mark.parametrize(
    "reply",
    [
        ok_reply(b"RIFF\x00\x00\x00\x00WAVEfmt "),
        httpx.Response(200, json={"request_id": "r", "audios": []}),
        httpx.Response(200, json={"request_id": "r", "audios": ["***not base64***"]}),
        httpx.Response(200, json=["unexpected"]),
        httpx.Response(200, text="not json"),
    ],
)
def test_synthesize_rejects_bad_audio(reply: httpx.Response) -> None:
    with (
        httpx.Client(transport=FakeSarvam([reply]).transport()) as client,
        pytest.raises(render.RenderError),
    ):
        render.synthesize(client, "k", {"text": "x"})


def test_is_mp3() -> None:
    assert render.is_mp3(b"ID3\x03rest")
    assert render.is_mp3(b"\xff\xfb\x90\x00")
    assert not render.is_mp3(b"RIFF....WAVE")
    assert not render.is_mp3(b"")


def test_resolve_api_key_sources(
    isolated_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    assert render.resolve_api_key(env_file, None, None) is None
    env_file.write_text("SARVAM_API_KEY=from-dotenv\n", encoding="utf-8")
    assert render.resolve_api_key(env_file, None, None) == "from-dotenv"
    monkeypatch.setenv("SARVAM_API_KEY", "from-env")
    assert render.resolve_api_key(env_file, None, None) == "from-env"


def test_resolve_from_ssm(aws: None, tmp_path: Path) -> None:
    ssm = boto3.client("ssm", region_name=REGION)
    ssm.put_parameter(Name="/jalsakshi/dev-x/sarvam_api_key", Value="from-ssm", Type="SecureString")
    ssm.put_parameter(Name="/jalsakshi/dev-x/prompts_bucket", Value="b-1", Type="String")
    assert render.resolve_api_key(tmp_path / ".env", "dev-x", ssm) == "from-ssm"
    assert render.resolve_bucket(None, "dev-x", ssm) == "b-1"
    assert render.resolve_bucket("explicit", "dev-x", ssm) == "explicit"
    assert render.resolve_api_key(tmp_path / ".env", "dev-missing", ssm) is None
    assert render.resolve_bucket(None, None, ssm) is None


def test_upload_to_s3(aws: None, cat: PromptCatalog, tmp_path: Path) -> None:
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="prompts-b", CreateBucketConfiguration={"LocationConstraint": REGION})
    jobs = render.plan(cat, tmp_path, render.Voice(), {}, only=["household.bye"])
    with pytest.raises(render.RenderError, match="missing clip"):
        render.upload(jobs, s3, "prompts-b", "prompts/hi")
    jobs[0].path.write_bytes(FAKE_MP3)
    assert render.upload(jobs, s3, "prompts-b", "/prompts/hi/") == ["prompts/hi/household.bye.mp3"]
    obj = s3.get_object(Bucket="prompts-b", Key="prompts/hi/household.bye.mp3")
    assert obj["ContentType"] == "audio/mpeg"
    assert obj["Body"].read() == FAKE_MP3


def test_main_dry_run_calls_nothing(
    isolated_env: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = render.main(
        ["--dry-run", "--out", str(tmp_path), "--bucket", "b"],
        transport=httpx.MockTransport(no_network),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "[render] operator.summary_dirty.n9" in out
    total = len(
        render.plan(
            render.PromptCatalog.from_file(render.prompts_path()),
            Path("unused"),
            render.Voice(),
            {},
        )
    )
    assert f"{total} clips, {total} to render" in out
    assert "s3://b/prompts/hi/" in out
    assert not list(tmp_path.iterdir())


def test_main_without_key_fails(isolated_env: None, tmp_path: Path) -> None:
    args = ["--out", str(tmp_path), "--env-file", str(tmp_path / "none.env")]
    assert render.main(args, transport=httpx.MockTransport(no_network)) == 2


def test_main_unknown_only_fails(isolated_env: None, tmp_path: Path) -> None:
    assert render.main(["--dry-run", "--out", str(tmp_path), "--only", "nope"]) == 1


def test_main_renders_and_uploads(
    aws: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SARVAM_API_KEY", "k")
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="b-2", CreateBucketConfiguration={"LocationConstraint": REGION})
    sarvam = FakeSarvam()
    args = [
        "--out",
        str(tmp_path),
        "--bucket",
        "b-2",
        "--only",
        "verify.greet",
        "--only",
        "operator.summary_dirty.n1",
    ]
    assert render.main(args, transport=sarvam.transport()) == 0
    assert len(sarvam.requests) == 2
    listed = s3.list_objects_v2(Bucket="b-2")["Contents"]
    assert sorted(o["Key"] for o in listed) == [
        "prompts/hi/operator.summary_dirty.n1.mp3",
        "prompts/hi/verify.greet.mp3",
    ]
    assert render.main(args, transport=httpx.MockTransport(no_network)) == 0
