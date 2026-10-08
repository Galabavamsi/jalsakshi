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
_Last updated Thu 8 Oct 2026, 22:30 IST (integration review). Nothing is deployed yet; everything below runs offline._

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
| First deploy of a dev stage (ap-south-1) | both | **todo, next** | Steps in README "Run it". Build the Lambda asset **before** `cdk deploy` |
| Bedrock model access: Claude Haiku 4.5 (`in.` profile), Nova 2 Lite (`global.` profile) | Vamsi | todo | Enable in ap-south-1, then one smoke brief per model; template fallback works without it |
| SSM secrets per stage: `vobiz_auth_id`, `vobiz_auth_token`, `vobiz_did`, `sarvam_api_key` | Vamsi | todo | `seed_demo.py --allowlist --ivr-token` writes `allowed_numbers` and `ivr_path_token` |
| Prompt audio: `prompts/render.py --stage` (Sarvam Bulbul → S3/CloudFront) | Vamsi | todo | After the Data stack exists; listen to one clip before uploading all 32 |
| Vobiz KYC + DID | Vamsi | todo | Blocks real PSTN calls only; the console simulator runs the same loop (`voice_provider=simulator`, labelled) |
| First real Hindi call (answer → digits → CheckIn) | Vamsi | todo | Confirms Gather timeout, Record callback and query strings on webhook URLs |
| Cognito users in role groups; console against the stage | Varun | todo | `admin-create-user` + `admin-add-user-to-group`; build web with stack outputs, redeploy Web stack |
| ARCHITECTURE.md contract sync | Varun | todo | Write in the builders' decisions: §4 answered = ANSWERED with a water answer, PARTIAL in VERIFY stays pending, `since`; §5 ESCALATED from every unresolved state and ESCALATED → OPERATOR_FIXED; §6 escalate waits for a fix, one extra verify round, verify targets, ticket id made in CheckInRun; §7 Cedar schema, `policy-evaluation-error`, `calls_today` counts reached DAILY calls; §8 new items (OPENTKT, OP copy, TKT#/META, CALL#…/STEP#, CALL#wait-, CALL#pending-, ACTIVITY#); §10 tools take no arguments; §13 `observed_7d.source`, brief `model_id`, close `409 verification_failed`, brief `403 stale-data`, event kinds UPPERCASE |
| Demo script, filming, edit | both | todo | `docs/DEMO_SCRIPT.md`; film Sat 10:00–18:00 (calls 09:00–21:00 only) |
| Builder Center blog | Vamsi | todo | separate prize (top 5 blogs) |

## Decisions log
- 2026-10-08: Track = Heat & Water; idea = JalSakshi (household-verified JJM tap supply in Chhattisgarh). Rejected: campus solar (no data access), Chhattisgarh stubble fires (out of season, crowded track; reused for the blog), tanker verification (summer only).
- 2026-10-08: Demo roles are acted and labelled; PHED side simulated and labelled.
- 2026-10-08: Calls go through a Vobiz DID with our Lambda serving the IVR, so call logic lives on AWS. Bolna is the fallback, and the web simulator is the last resort.
