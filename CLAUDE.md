# CLAUDE.md: JalSakshi

JalSakshi (जल साक्षी, "water witness") is a Hindi phone check-in that asks village households whether Jal Jeevan Mission tap water actually came. It opens repair tickets for the pump operator and closes them only when the same households confirm water is back. The output is evidence for the Gram Sabha's Har Ghar Jal certification and handover decisions.

Hackathon: WeMakeDevs × AWS "Environmental Hacks", **Heat & Water track**. Deadline **Sun 11 Oct 2026, 20:00 IST**. Judging criteria: impact, built on AWS (must be visible in the video), usability, a working loop, and a 3-minute video.

Read `docs/ARCHITECTURE.md` (the build contract) and `docs/HANDOVER.md` (who is doing what right now) before changing code.

## Rules
- **Decisions are deterministic.** Day status, ticket transitions and calling permissions live in `core/` and `policy/`, as pure tested code. The LLM (`agent/`) only extracts free speech and writes prose, and it always has a template fallback. Never let a model decide a status.
- **Every number shown to a user carries its source and freshness** (`SourceTag`). Simulated or replayed data is labelled `simulated` or `replay`, everywhere.
- **Never place calls to real government helplines** (PHED 1800-233-0008, etc.) or to any number without consent on file. Calls only between 09:00 and 21:00 IST.
- **Region is `ap-south-1`.** Pass it explicitly to every boto3 client, CDK env and Strands `BedrockModel` (the shell has `AWS_REGION=us-east-1` for other work). Bedrock model IDs: `in.anthropic.claude-haiku-4-5-20251001-v1:0` → `global.amazon.nova-2-lite-v1:0` → template.
- **Secrets** go in SSM Parameter Store `/jalsakshi/{stage}/…` (deployed) or `.env` (local, gitignored). Never commit keys, and never paste them into code or docs.
- **Do not run Claude Code itself through Bedrock** (`CLAUDE_CODE_USE_BEDROCK` must be unset); use the Team plan.
- Never stage `D:\hackathons\.scratch` or any research dumps; the repo holds only work done during the event.

## Layout
```
src/jalsakshi/{core,policy,store,voice,agent,data,handlers}/   Python package (3.12)
infra/        AWS CDK app (Python): stacks + Step Functions
web/          operator console (React + Vite + TS)
prompts/      Hindi prompt text (hi.yaml) + audio render script
tests/        pytest (unit + property tests); mirrors src/
docs/         ARCHITECTURE, HANDOVER, DEMO_SCRIPT, RESEARCH
```
Ownership: **Vamsi** owns voice, agent, data and prompts. **Varun** owns core, policy, store, infra and web. Edit the other person's module only after a heads-up in `docs/HANDOVER.md`.

## Commands (Windows, PowerShell or bash)
```
uv sync --all-groups                      # install Python deps
uv run ruff check . ; uv run ruff format . # lint / format
uv run pytest -q                          # all tests (no AWS needed; boto3 stubbed with moto)
uv run python scripts/build_lambda.py     # ALWAYS before deploy: builds build/lambda (Linux wheels)
cd infra ; npx aws-cdk@2 deploy --all -c stage=dev-<name> [-c voice_provider=vobiz]   # your own stack
uv run python scripts/seed_demo.py --stage dev-<name> --allowlist --ivr-token --schedules
uv run python prompts/render.py --stage dev-<name>   # render Hindi prompts with Sarvam → S3
cd web ; pnpm install ; pnpm dev           # console on localhost (VITE_API_MODE=mock works offline)
```
Each developer deploys their own stage (`dev-vamsi`, `dev-varun`). Only `demo` is used for recording, deployed from `main`.

## Definition of done (per PR)
Tests pass, ruff is clean, the docs touched by the change are updated, `docs/HANDOVER.md` status line is updated, and there are no secrets in the diff.
