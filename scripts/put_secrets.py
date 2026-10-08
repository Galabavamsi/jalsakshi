"""Copy vendor keys from the local .env into SSM SecureString parameters for one stage.

Usage:  uv run python scripts/put_secrets.py --stage dev-<name> [--profile aws-main]

Writes /jalsakshi/<stage>/{vobiz_auth_id, vobiz_auth_token, vobiz_did, sarvam_api_key}.
Prints parameter names only; values never reach stdout or logs.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv

ENV_TO_PARAM = {
    "VOBIZ_AUTH_ID": "vobiz_auth_id",
    "VOBIZ_AUTH_TOKEN": "vobiz_auth_token",
    "VOBIZ_DID": "vobiz_did",
    "SARVAM_API_KEY": "sarvam_api_key",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", required=True)
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    parser.add_argument("--region", default=os.environ.get("JALSAKSHI_REGION", "ap-south-1"))
    parser.add_argument("--env-file", default=str(Path(__file__).parents[1] / ".env"))
    args = parser.parse_args(argv)

    load_dotenv(args.env_file)
    ssm = boto3.Session(profile_name=args.profile, region_name=args.region).client("ssm")
    missing = [key for key in ENV_TO_PARAM if not os.environ.get(key, "").strip()]
    if missing:
        print("missing in .env: " + ", ".join(missing), file=sys.stderr)
        return 1
    for env_key, param in ENV_TO_PARAM.items():
        name = f"/jalsakshi/{args.stage}/{param}"
        ssm.put_parameter(
            Name=name, Value=os.environ[env_key].strip(), Type="SecureString", Overwrite=True
        )
        print(f"wrote {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
