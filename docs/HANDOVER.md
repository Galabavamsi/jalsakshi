# Handover and status board

Update the **Status** table whenever you start or finish something. This is how two people (and their Claude sessions) avoid stepping on each other.

## How to pick this up (new teammate or new Claude session)
1. Read `CLAUDE.md`, then `docs/ARCHITECTURE.md`, then this file.
2. `git pull`, then `uv sync --all-groups`, then `uv run pytest -q`.
3. Check the **Status** table: take an unowned task, or continue your own.
4. Branch as `feat/<module>-<thing>`, open a PR to `main`, and update this file in the same PR.

## Accounts and keys (never commit them; put them in `.env` locally and in SSM `/jalsakshi/<stage>/` when deployed)
| Key | Who has it | SSM name |
|---|---|---|
| AWS account 301745146083 (`aws-main` profile, ap-south-1) | both | n/a |
| Sarvam API key | Vamsi | `sarvam_api_key` |
| Vobiz auth ID + token, DID number | Vamsi (KYC) | `vobiz_auth_id`, `vobiz_auth_token`, `vobiz_did` |
| Bolna API key (fallback) | Vamsi | `bolna_api_key` |
| Consenting test phone numbers | both | `.env` only (`TEST_NUMBERS`) |

## Timeline (IST)
| When | Goal |
|---|---|
| Thu 8 Oct night | Repo, CDK skeleton, first deploy; **voice spike: one real Hindi call with keypad input answered by our Lambda** |
| Fri 9 Oct | Core loop end to end: check-in → reconcile → ticket → operator → verify. Tests green |
| Sat 10 Oct | Console, Gram Sabha sheet, dashboard; **film 10:00–18:00** (calls only 09:00–21:00) |
| Sun 11 Oct | Polish, README, architecture diagram, Builder Center blog. **Video locked 16:00, submit by 19:00** |

## Status
_Last updated Fri 9 Oct 2026, 00:20 IST. Stage **dev-vamsi** is deployed in ap-south-1: API https://pcin3mmqo8.execute-api.ap-south-1.amazonaws.com, console https://d3axprdstjr7n8.cloudfront.net, prompt audio https://d2l0x4lf85o8ao.cloudfront.net/prompts/hi. Voice provider is still `simulator`._

| Area | Owner | State | Notes |
|---|---|---|---|
| Repo, docs, conventions, `core/models.py` contract, API contract (§13) | Claude | done | |
| core: reconciler r1, ticket state machine, verification, IST clock, ids | Varun (Claude build) | done, tested | 209 tests incl. hypothesis properties (quorum, monotonic NO, permutation, replay) |
| policy: Cedar policies + schema, `can_*` helpers, Hindi/English reasons | Varun (Claude build) | done, tested | 100 tests; fails closed with `policy-evaluation-error` |
| store: DynamoDB single table, conditional writes, optimistic lock | Varun (Claude build) | done, tested | 62 tests (moto) |
| voice: flow engine, Vobiz XML adapter, simulator adapter, prompt catalog | Vamsi (Claude build) | done, tested offline | 210 tests; Vobiz Gather/Record timing unverified on a real call |
| agent: note extraction, Gram Sabha brief, model chain → template | Vamsi (Claude build) | done, tested offline | 71 tests; no live Bedrock call made yet |
| data: IMIS HGJ, CGWB groundwater, Open-Meteo rain | Vamsi (Claude build) | done, tested | 68 tests; one live read-only GET per source worked on 8 Oct |
| handlers, infra (CDK: Data/Web/App/Obs stacks, CheckInRun + TicketFlow), scripts | Claude build | done, synth OK | 109 tests incl. full loop end to end; `cdk synth` clean with fake creds |
| web console (React + Vite + Cognito PKCE) | Varun (Claude build) | done, mock mode checked | 61 vitest, lint + build clean; Cognito sign-in untested |
| Integration review | Claude | **done 8 Oct** | 831 pytest + 61 vitest pass, ruff clean. Fixed: stale `uv.lock` (added aws-xray-sdk, tzdata), simulator answers now labelled `simulated` (API + console), console understands backend ticket event kinds (`NOTIFIED`…, `NOTE` + `detail.note`) and `operator:<id>` actors, nullable `stage_pct`, brief `model_id`, CI web job + `uv sync --locked` |
| First deploy of a dev stage (ap-south-1) | Claude | **done 9 Oct 00:00** | `dev-vamsi`: 4 stacks, 14 Lambdas, Lambda asset 58.9 MB. API smoke OK (villages 200, brief 403 Cedar stale-data as designed) |
| Bedrock model access: Claude Haiku 4.5 (`in.` profile), Nova 2 Lite (`global.` profile) | Vamsi | done | Both answered a test call from ap-south-1 on 8 Oct; first live brief needs a check-in day |
| SSM secrets per stage: `vobiz_auth_id`, `vobiz_auth_token`, `vobiz_did`, `sarvam_api_key` | Claude | done (dev-vamsi) | `scripts/put_secrets.py --stage <stage>` copies them from `.env`; seed wrote `allowed_numbers` + `ivr_path_token`; 2 demo villages seeded (no schedules yet) |
| Prompt audio: `prompts/render.py --stage` (Sarvam Bulbul → S3/CloudFront) | Claude | done | 32 clips uploaded, CDN serves audio/mpeg |
| Vobiz KYC + DID | Vamsi | done | DID +918064260325 (₹500/mo, next bill 7 Nov) |
| First real call (answer → digits → reply → hangup webhook) | Claude + Vamsi | **done 8 Oct 21:35** via a spike Lambda; next: redeploy with `-c voice_provider=vobiz` and run the real stack loop (09:00–21:00 only) |
| Cognito users in role groups; console against the stage | Varun | todo | `admin-create-user` + `admin-add-user-to-group`; build web with stack outputs, redeploy Web stack |
| Context refresh (IMIS HGJ, CGWB groundwater, rain) | Claude | done | India-WRIS times out from AWS, so it falls back to a bundled, labelled CGWB 2025 snapshot (`scripts/snapshot_cgwb.py`) |
| ARCHITECTURE.md contract sync | Varun | todo | Write in the builders' decisions: §4 answered = ANSWERED with a water answer, PARTIAL in VERIFY stays pending, `since`; §5 ESCALATED from every unresolved state and ESCALATED → OPERATOR_FIXED; §6 escalate waits for a fix, one extra verify round, verify targets, ticket id made in CheckInRun; §7 Cedar schema, `policy-evaluation-error`, `calls_today` counts reached DAILY calls; §8 new items (OPENTKT, OP copy, TKT#/META, CALL#…/STEP#, CALL#wait-, CALL#pending-, ACTIVITY#); §10 tools take no arguments; §13 `observed_7d.source`, brief `model_id`, close `409 verification_failed`, brief `403 stale-data`, event kinds UPPERCASE |
| Demo script, filming, edit | both | todo | `docs/DEMO_SCRIPT.md`; film Sat 10:00–18:00 (calls 09:00–21:00 only) |
| Builder Center blog | Vamsi | todo | separate prize (top 5 blogs) |

## Decisions log
- 2026-10-08: Track = Heat & Water; idea = JalSakshi (household-verified JJM tap supply in Chhattisgarh). Rejected: campus solar (no data access), Chhattisgarh stubble fires (out of season, crowded track; reused for the blog), tanker verification (summer only).
- 2026-10-08: Demo roles are acted and labelled; PHED side simulated and labelled.
- 2026-10-08: Calls go through a Vobiz DID with our Lambda serving the IVR, so call logic lives on AWS. Bolna is the fallback, and the web simulator is the last resort.
