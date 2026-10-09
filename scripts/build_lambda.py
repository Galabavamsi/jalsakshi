"""Build the shared Lambda code asset in build/lambda (CPython 3.12, x86_64, Amazon Linux).

    uv run --no-sync python scripts/build_lambda.py [--source-only] [--platform PLATFORM]

1. Export the locked runtime dependencies from uv.lock (no dev or infra groups), minus the
   packages the Lambda runtime already ships (boto3, botocore, s3transfer, jmespath).
2. Install them as manylinux wheels for CPython 3.12 into the output folder (``--no-deps``:
   the export is already the full, pinned dependency closure).
3. Copy src/jalsakshi (including the Cedar policy files) and prompts/hi.yaml (served to the
   functions through JALSAKSHI_PROMPTS_PATH=/var/task/prompts/hi.yaml).
4. Write the marker file that tells the CDK app the asset is real.

``--source-only`` refreshes only the code and prompts, keeping installed dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REPO: Final = Path(__file__).resolve().parents[1]
DEFAULT_OUT: Final = REPO / "build" / "lambda"
DEFAULT_PLATFORM: Final = "x86_64-manylinux2014"
PYTHON_VERSION: Final = "3.12"
RUNTIME_PROVIDED: Final = frozenset({"boto3", "botocore", "s3transfer", "jmespath"})
MARKER: Final = ".jalsakshi-build.json"
MAX_UNZIPPED_BYTES: Final = 250 * 1024 * 1024
REQUIRED_FILES: Final = (
    "jalsakshi/policy/policies/jalsakshi.cedar",
    "jalsakshi/policy/policies/jalsakshi.cedarschema",
    "jalsakshi/handlers/api.py",
    "prompts/hi.yaml",
)
EXPORT_CMD: Final = (
    "uv",
    "export",
    "--locked",
    "--no-dev",
    "--no-emit-project",
    "--no-hashes",
    "--no-annotate",
    "--no-header",
    "--format",
    "requirements-txt",
)

type Runner = Callable[..., subprocess.CompletedProcess[str]]


class BuildError(RuntimeError):
    """The asset could not be built; the message says what to do."""


def normalise(name: str) -> str:
    """PEP 503 project-name normalisation."""
    return re.sub(r"[-_.]+", "-", name).lower()


def filter_requirements(text: str, exclude: Iterable[str]) -> list[str]:
    """Pinned requirement lines from ``uv export``, without comments or excluded projects."""
    excluded = {normalise(name) for name in exclude}
    kept: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-", ".")):
            continue
        name = re.split(r"[\s;=<>!~\[@]", line, maxsplit=1)[0]
        if normalise(name) not in excluded:
            kept.append(line)
    return kept


def export_requirements(runner: Runner) -> str:
    """The locked runtime dependency closure as requirements text."""
    result = runner(list(EXPORT_CMD), cwd=REPO, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise BuildError(
            "uv export failed (is uv.lock up to date? run `uv lock` or `uv sync`):\n"
            + (result.stderr or result.stdout)[-2000:]
        )
    return result.stdout


def install_requirements(
    requirements: Sequence[str], out: Path, platform: str, runner: Runner
) -> None:
    """Install manylinux wheels for CPython 3.12 into ``out``."""
    req_file = out.parent / "requirements-lambda.txt"
    req_file.write_text("\n".join(requirements) + "\n", encoding="utf-8")
    cmd = [
        "uv",
        "pip",
        "install",
        "--target",
        str(out),
        "--python-platform",
        platform,
        "--python-version",
        PYTHON_VERSION,
        "--only-binary",
        ":all:",
        "--no-deps",
        "-r",
        str(req_file),
    ]
    result = runner(cmd, cwd=REPO, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise BuildError("uv pip install failed:\n" + (result.stderr or result.stdout)[-2000:])


def copy_sources(out: Path) -> None:
    """Copy the jalsakshi package (with non-Python policy files) and the prompt catalog."""
    package = out / "jalsakshi"
    if package.exists():
        shutil.rmtree(package)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(REPO / "src" / "jalsakshi", package, ignore=ignore)
    prompts = out / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    for catalog in sorted((REPO / "prompts").glob("*.yaml")):  # every call language
        shutil.copy2(catalog, prompts / catalog.name)


def prune(out: Path) -> None:
    """Drop console scripts and bytecode caches the functions never use."""
    shutil.rmtree(out / "bin", ignore_errors=True)
    for cache in out.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def check_asset(out: Path) -> int:
    """Verify required files exist and the asset fits Lambda's 250 MB unzipped limit."""
    missing = [name for name in REQUIRED_FILES if not (out / name).is_file()]
    if missing:
        raise BuildError(f"asset is missing {', '.join(missing)}")
    size = sum(path.stat().st_size for path in out.rglob("*") if path.is_file())
    if size > MAX_UNZIPPED_BYTES:
        raise BuildError(f"asset is {size / 2**20:.0f} MiB, over Lambda's 250 MB limit")
    return size


def write_marker(out: Path, info: dict[str, Any]) -> None:
    """Record how the asset was built (the CDK app checks this file exists)."""
    (out / MARKER).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def build(
    out: Path,
    *,
    platform: str = DEFAULT_PLATFORM,
    exclude: Iterable[str] = RUNTIME_PROVIDED,
    source_only: bool = False,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Build the asset and return the marker information."""
    if source_only and not (out / MARKER).is_file():
        raise BuildError("--source-only needs a full build first")
    requirements: list[str] = []
    if not source_only:
        requirements = filter_requirements(export_requirements(runner), exclude)
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        install_requirements(requirements, out, platform, runner)
    copy_sources(out)
    prune(out)
    size = check_asset(out)
    info = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "platform": platform,
        "python_version": PYTHON_VERSION,
        "requirements": len(requirements) if not source_only else "unchanged",
        "excluded": sorted(normalise(name) for name in exclude),
        "size_bytes": size,
    }
    write_marker(out, info)
    return info


def main(argv: Sequence[str] | None = None, *, runner: Runner = subprocess.run) -> int:
    """CLI entrypoint; returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--platform", default=DEFAULT_PLATFORM)
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument(
        "--include-boto3",
        action="store_true",
        help="bundle boto3/botocore too instead of using the Lambda runtime's copy",
    )
    args = parser.parse_args(argv)
    exclude = () if args.include_boto3 else RUNTIME_PROVIDED
    try:
        info = build(
            args.out,
            platform=args.platform,
            exclude=exclude,
            source_only=args.source_only,
            runner=runner,
        )
    except BuildError as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 1
    print(f"built {args.out} ({info['size_bytes'] / 2**20:.1f} MiB, {info['platform']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
