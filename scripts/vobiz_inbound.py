"""Route missed calls on the stage's Vobiz number to JalSakshi (ARCHITECTURE.md §15.4).

Creates (or updates) a Vobiz Application whose answer URL is the stage's secret
``/ivr/vobiz/{token}/inbound`` webhook, then attaches the DID to it. Secrets are read from SSM
and never printed.

    uv run --no-sync python scripts/vobiz_inbound.py --stage dev-<name> [--dry-run] [--detach]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

import httpx

REPO: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from seed_demo import REGION, load_env, stack_outputs  # noqa: E402

API: Final = "https://api.vobiz.ai/api/v1/Account"


def ssm_value(ssm: Any, stage: str, name: str) -> str:
    response = ssm.get_parameter(Name=f"/jalsakshi/{stage}/{name}", WithDecryption=True)
    return str(response["Parameter"]["Value"]).strip()


def main(argv: Sequence[str] | None = None) -> int:
    env = load_env()
    parser = argparse.ArgumentParser(description="Attach the Vobiz DID to JalSakshi's webhook.")
    parser.add_argument("--stage", default=env.get("STAGE"))
    parser.add_argument("--profile", default=env.get("AWS_PROFILE"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--detach", action="store_true", help="unlink the number again")
    args = parser.parse_args(argv)
    import boto3

    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    ssm = session.client("ssm", region_name=REGION)
    auth_id = ssm_value(ssm, args.stage, "vobiz_auth_id")
    headers = {
        "X-Auth-ID": auth_id,
        "X-Auth-Token": ssm_value(ssm, args.stage, "vobiz_auth_token"),
        "Content-Type": "application/json",
    }
    did = ssm_value(ssm, args.stage, "vobiz_did")
    did = did if did.startswith("+") else f"+{did}"
    token = ssm_value(ssm, args.stage, "ivr_path_token")
    api_url = stack_outputs(session.client("cloudformation", region_name=REGION), args.stage)[
        "ApiUrl"
    ].rstrip("/")
    base = f"{api_url}/ivr/vobiz/{token}"
    app_name = f"jalsakshi-{args.stage}-inbound"
    body = {
        "app_name": app_name,
        "answer_url": f"{base}/inbound",
        "answer_method": "POST",
        "hangup_url": f"{base}/status",
        "hangup_method": "POST",
        "fallback_answer_url": f"{base}/inbound",
        "fallback_method": "POST",
        "application_type": "XML",
    }
    number_path = f"{API}/{auth_id}/numbers/{quote(did, safe='')}/application"
    masked = f"{did[:5]}XXXX{did[-4:]}"
    print(f"stage {args.stage}: number {masked} -> {api_url}/ivr/vobiz/<token>/inbound")
    if args.dry_run:
        return 0
    with httpx.Client(timeout=20, headers=headers) as http:
        if args.detach:
            response = http.delete(number_path)
            print(f"detach: HTTP {response.status_code}")
            return 0 if response.status_code < 300 else 1
        listed = http.get(f"{API}/{auth_id}/Application/").json().get("objects", [])
        existing = next((a for a in listed if a.get("app_name") == app_name), None)
        if existing:
            app_id = str(existing["app_id"])
            response = http.post(f"{API}/{auth_id}/Application/{app_id}/", json=body)
            print(f"application updated: HTTP {response.status_code}")
        else:
            response = http.post(f"{API}/{auth_id}/Application/", json=body)
            print(f"application created: HTTP {response.status_code}")
            if response.status_code >= 300:
                print(response.text[:300])
                return 1
            app_id = str(response.json()["app_id"])
        attach = http.post(number_path, json={"application_id": app_id})
        print(f"number attached: HTTP {attach.status_code}")
        return 0 if attach.status_code < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
