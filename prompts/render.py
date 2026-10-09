"""Render the Hindi prompt catalog to 8 kHz MP3 with Sarvam Bulbul, and optionally upload to S3.

Usage (from the repo root):
    uv run python prompts/render.py --dry-run              # list clips; no API calls, no key
    uv run python prompts/render.py                        # write prompts/out/hi/<key>.mp3
    uv run python prompts/render.py --bucket NAME          # also upload to s3://NAME/prompts/hi/
    uv run python prompts/render.py --stage dev-vamsi      # key and bucket from SSM if not local

Every prompt in prompts/hi.yaml is rendered, plus n1..n9 variants of prompts with one placeholder
(for example ``operator.summary_no_supply.n3``). Clips whose text and voice settings are unchanged
since the last run (``manifest.json`` in the output folder) are skipped unless ``--force``.

SARVAM_API_KEY comes from the environment, then ``.env``, then (with ``--stage``) SSM
``/jalsakshi/<stage>/sarvam_api_key``. With ``--stage`` and no ``--bucket``, the bucket name is
read from SSM ``/jalsakshi/<stage>/prompts_bucket``. AWS calls use $JALSAKSHI_REGION (ap-south-1).

Sarvam text-to-speech REST API (read 2026-10-08):
https://docs.sarvam.ai/api-reference/text-to-speech/convert and
https://docs.sarvam.ai/api/getting-started/models/bulbul
POST https://api.sarvam.ai/text-to-speech, header ``api-subscription-key``, JSON body
``{text, language_code, model, speaker, pace, speech_sample_rate, output_audio_codec}``;
the response is ``{request_id, audios: [base64 audio]}``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jalsakshi.voice.catalog import PromptCatalog, prompts_path  # noqa: E402

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
DEFAULT_MODEL = "bulbul:v3"
DEFAULT_SPEAKER = "ritu"
DEFAULT_PACE = 0.9
SAMPLE_RATE_HZ = 8000
AUDIO_CODEC = "mp3"
DEFAULT_OUT_DIR = ROOT / "prompts" / "out" / "hi"
DEFAULT_PREFIX = "prompts/hi"
MANIFEST_NAME = "manifest.json"
REGION_ENV = "JALSAKSHI_REGION"
DEFAULT_REGION = "ap-south-1"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
HTTP_TIMEOUT_S = 60.0


class RenderError(RuntimeError):
    """A clip could not be rendered or uploaded."""


@dataclass(frozen=True, slots=True)
class Voice:
    """Bulbul settings; part of each clip's fingerprint, so a change re-renders everything."""

    model: str = DEFAULT_MODEL
    speaker: str = DEFAULT_SPEAKER
    pace: float = DEFAULT_PACE
    sample_rate_hz: int = SAMPLE_RATE_HZ
    temperature: float | None = None

    def payload(self, text: str, language: str) -> dict[str, Any]:
        """JSON body for one Sarvam text-to-speech request."""
        body: dict[str, Any] = {
            "text": text,
            "language_code": language,
            "model": self.model,
            "speaker": self.speaker,
            "pace": self.pace,
            "speech_sample_rate": self.sample_rate_hz,
            "output_audio_codec": AUDIO_CODEC,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        return body

    def fingerprint(self, text: str, language: str) -> str:
        """Stable hash of everything that changes the audio."""
        canonical = json.dumps(self.payload(text, language), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Job:
    """One clip: where it goes and whether it needs (re-)rendering."""

    key: str
    text: str
    path: Path
    fingerprint: str
    stale: bool


@dataclass(slots=True)
class Result:
    """What a run did."""

    rendered: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    uploaded: list[str] = field(default_factory=list)


def plan(
    catalog: PromptCatalog,
    out_dir: Path,
    voice: Voice,
    manifest: dict[str, str],
    only: Sequence[str] = (),
    force: bool = False,
) -> list[Job]:
    """Clips to consider, marking each stale if missing, changed, or forced."""
    wanted = set(only)
    unknown = wanted - set(catalog.audio_keys())
    if unknown:
        raise RenderError(f"unknown prompt keys: {sorted(unknown)}")
    jobs = []
    for key, text in catalog.render_items():
        if wanted and key not in wanted:
            continue
        path = out_dir / f"{key}.mp3"
        digest = voice.fingerprint(text, catalog.language)
        stale = force or not path.is_file() or manifest.get(key) != digest
        jobs.append(Job(key=key, text=text, path=path, fingerprint=digest, stale=stale))
    return jobs


def load_manifest(out_dir: Path) -> dict[str, str]:
    """``{key: fingerprint}`` of clips already rendered into ``out_dir``."""
    path = out_dir / MANIFEST_NAME
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in data.items()}


def save_manifest(out_dir: Path, manifest: dict[str, str]) -> None:
    """Write the manifest next to the clips."""
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(sorted(manifest.items())), indent=2)
    (out_dir / MANIFEST_NAME).write_text(text + "\n", encoding="utf-8")


def is_mp3(data: bytes) -> bool:
    """True for an ID3-tagged file or a bare MPEG audio frame."""
    if data.startswith(b"ID3"):
        return True
    return len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def synthesize(
    client: httpx.Client,
    api_key: str,
    payload: dict[str, Any],
    *,
    attempts: int = 3,
    backoff_s: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """Call Sarvam TTS once (retrying 429/5xx) and return the decoded MP3 bytes."""
    headers = {"api-subscription-key": api_key, "Content-Type": "application/json"}
    for attempt in range(1, attempts + 1):
        response = client.post(SARVAM_TTS_URL, json=payload, headers=headers)
        if response.status_code in RETRY_STATUSES and attempt < attempts:
            sleep(backoff_s * attempt)
            continue
        if response.status_code != httpx.codes.OK:
            raise RenderError(f"Sarvam TTS failed: HTTP {response.status_code} {_error(response)}")
        return _decode_audio(response)
    raise RenderError("Sarvam TTS failed after retries")  # pragma: no cover - loop always returns


def render(
    jobs: Sequence[Job],
    client: httpx.Client,
    api_key: str,
    voice: Voice,
    language: str,
    out_dir: Path,
    manifest: dict[str, str],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> Result:
    """Render every stale job to disk, saving the manifest after each clip."""
    result = Result()
    for job in jobs:
        if not job.stale:
            result.skipped.append(job.key)
            continue
        audio = synthesize(client, api_key, voice.payload(job.text, language), sleep=sleep)
        job.path.parent.mkdir(parents=True, exist_ok=True)
        job.path.write_bytes(audio)
        manifest[job.key] = job.fingerprint
        save_manifest(out_dir, manifest)
        result.rendered.append(job.key)
    return result


def upload(jobs: Sequence[Job], s3_client: Any, bucket: str, prefix: str) -> list[str]:
    """Upload every rendered clip to ``s3://bucket/prefix/<key>.mp3``; returns the object keys."""
    keys = []
    for job in jobs:
        if not job.path.is_file():
            raise RenderError(f"missing clip {job.path}; render it before uploading")
        object_key = f"{prefix.strip('/')}/{job.key}.mp3"
        s3_client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=job.path.read_bytes(),
            ContentType="audio/mpeg",
            CacheControl="public, max-age=300",
        )
        keys.append(object_key)
    return keys


def resolve_api_key(env_file: Path, stage: str | None, ssm_client: Any | None) -> str | None:
    """SARVAM_API_KEY from the environment, then ``.env``, then SSM (only with a stage)."""
    key = os.environ.get("SARVAM_API_KEY") or read_env_file(env_file).get("SARVAM_API_KEY")
    if key:
        return key
    if stage and ssm_client is not None:
        return _ssm_value(ssm_client, f"/jalsakshi/{stage}/sarvam_api_key")
    return None


def resolve_bucket(bucket: str | None, stage: str | None, ssm_client: Any | None) -> str | None:
    """Bucket from ``--bucket``, else SSM ``/jalsakshi/<stage>/prompts_bucket``, else None."""
    if bucket:
        return bucket
    if stage and ssm_client is not None:
        return _ssm_value(ssm_client, f"/jalsakshi/{stage}/prompts_bucket")
    return None


def read_env_file(path: Path) -> dict[str, str]:
    """Non-empty values from a dotenv file (missing file means no values)."""
    if not path.is_file():
        return {}
    from dotenv import dotenv_values

    return {key: value for key, value in dotenv_values(path).items() if value}


def build_parser() -> argparse.ArgumentParser:
    """Command-line options."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--catalog", type=Path, default=None, help="prompt YAML (default hi.yaml)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output folder")
    parser.add_argument("--only", action="append", default=[], metavar="KEY", help="clip key")
    parser.add_argument("--force", action="store_true", help="re-render unchanged clips")
    parser.add_argument("--dry-run", action="store_true", help="list clips; call nothing")
    parser.add_argument("--bucket", help="S3 bucket to upload to")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="S3 key prefix")
    parser.add_argument("--stage", help="stage for SSM lookups, e.g. dev-vamsi")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env", help="dotenv file")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Sarvam TTS model")
    parser.add_argument("--speaker", default=DEFAULT_SPEAKER, help="Bulbul speaker (lowercase)")
    parser.add_argument("--pace", type=float, default=DEFAULT_PACE, help="0.5 to 2.0")
    parser.add_argument("--temperature", type=float, default=None, help="0.01 to 2.0")
    return parser


def main(argv: Sequence[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    args = build_parser().parse_args(argv)
    catalog = PromptCatalog.from_file(args.catalog or prompts_path())
    voice = Voice(args.model, args.speaker, args.pace, SAMPLE_RATE_HZ, args.temperature)
    try:
        manifest = load_manifest(args.out)
        jobs = plan(catalog, args.out, voice, manifest, args.only, args.force)
        if args.dry_run:
            _print_plan(jobs, args)
            return 0
        return _run(jobs, catalog, voice, manifest, args, transport)
    except RenderError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _run(
    jobs: Sequence[Job],
    catalog: PromptCatalog,
    voice: Voice,
    manifest: dict[str, str],
    args: argparse.Namespace,
    transport: httpx.BaseTransport | None,
) -> int:
    ssm = _aws_client("ssm") if args.stage else None
    api_key = resolve_api_key(args.env_file, args.stage, ssm)
    if any(job.stale for job in jobs) and not api_key:
        print("error: SARVAM_API_KEY is not set (env, .env or SSM)", file=sys.stderr)
        return 2
    with httpx.Client(timeout=HTTP_TIMEOUT_S, transport=transport) as client:
        result = render(jobs, client, api_key or "", voice, catalog.language, args.out, manifest)
    print(f"rendered {len(result.rendered)}, unchanged {len(result.skipped)} -> {args.out}")
    bucket = resolve_bucket(args.bucket, args.stage, ssm)
    if bucket:
        uploaded = upload(jobs, _aws_client("s3"), bucket, args.prefix)
        print(f"uploaded {len(uploaded)} clips to s3://{bucket}/{args.prefix.strip('/')}/")
    return 0


def _print_plan(jobs: Sequence[Job], args: argparse.Namespace) -> None:
    for job in jobs:
        status = "render" if job.stale else "cached"
        print(f"[{status}] {job.key} -> {job.path}\n    {job.text}")
    stale = sum(job.stale for job in jobs)
    print(f"{len(jobs)} clips, {stale} to render (dry run: nothing called)")
    if args.bucket:
        print(f"would upload to s3://{args.bucket}/{args.prefix.strip('/')}/")
    elif args.stage:
        print(f"would upload to the bucket in SSM /jalsakshi/{args.stage}/prompts_bucket")


def _decode_audio(response: httpx.Response) -> bytes:
    try:
        body = response.json()
        audios = body.get("audios") if isinstance(body, dict) else None
        audio = base64.b64decode("".join(audios or []), validate=True)
    except (ValueError, TypeError) as error:
        raise RenderError(f"Sarvam TTS returned an unreadable body: {error}") from error
    if not audio:
        raise RenderError("Sarvam TTS returned no audio")
    if not is_mp3(audio):
        raise RenderError("Sarvam TTS did not return MP3 audio")
    return audio


def _error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    error = body.get("error") if isinstance(body, dict) else None
    return str(error.get("message", "")) if isinstance(error, dict) else ""


def _ssm_value(ssm_client: Any, name: str) -> str | None:
    try:
        reply = ssm_client.get_parameter(Name=name, WithDecryption=True)
    except ssm_client.exceptions.ParameterNotFound:
        return None
    return reply["Parameter"]["Value"] or None


def _aws_client(service: str) -> Any:
    import boto3

    return boto3.client(service, region_name=os.environ.get(REGION_ENV, DEFAULT_REGION))


if __name__ == "__main__":
    sys.exit(main())
