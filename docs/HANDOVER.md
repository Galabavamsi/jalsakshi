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
| Area | Owner | State | Notes |
|---|---|---|---|
| Repo, docs, conventions | Claude | done | this commit |
| core: models, reconciler, tickets + tests | Varun | todo | spec §3–5 |
| policy: Cedar + wrapper + tests | Varun | todo | spec §7 |
| store: DynamoDB repo | Varun | todo | spec §8 |
| infra: CDK stacks, Step Functions | Varun | todo | spec §6 |
| voice: flow engine, Vobiz adapter, simulator | Vamsi | todo | spec §9 |
| prompts: hi.yaml + Sarvam render | Vamsi | todo | spec §9 |
| agent: notes + Gram Sabha brief | Vamsi | todo | spec §10 |
| data: IMIS, CGWB, Open-Meteo | Vamsi | todo | spec §11 |
| web: operator console | Varun | todo | villages, tickets, brief, phone simulator |
| Vobiz KYC + DID | Vamsi | todo | blocks real PSTN calls |
| Demo script, filming, edit | both | todo | `docs/DEMO_SCRIPT.md` |
| Builder Center blog | Vamsi | todo | separate prize (top 5 blogs) |

## Decisions log
- 2026-10-08: Track = Heat & Water; idea = JalSakshi (household-verified JJM tap supply in Chhattisgarh). Rejected: campus solar (no data access), Chhattisgarh stubble fires (out of season, crowded track; reused for the blog), tanker verification (summer only).
- 2026-10-08: Demo roles are acted and labelled; PHED side simulated and labelled.
- 2026-10-08: Calls go through a Vobiz DID with our Lambda serving the IVR, so call logic lives on AWS. Bolna is the fallback, and the web simulator is the last resort.
