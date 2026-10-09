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
| Sat 10 Oct | Console, Gram Sabha sheet, dashboard; **film 10:00–18:00** |
| Sun 11 Oct | Polish, README, architecture diagram, Builder Center blog. **Video locked 16:00, submit by 19:00** |

## Status
_Last updated Sat 10 Oct 2026, 00:25 IST. Stage **dev-vamsi** is deployed in ap-south-1: console https://jalsakshi.humanslop.in, API https://pcin3mmqo8.execute-api.ap-south-1.amazonaws.com, prompt audio https://d2l0x4lf85o8ao.cloudfront.net/prompts/{hi,hne}. Voice provider **vobiz**, missed-call number +91 80 6426 0325. Console logins `vamsi` and `varun` (ADMIN + Panchayat Secretary); public sign-up is off, Panchayat logins are made from More → Set up a Panchayat. No calling-hours window. **Stage reset 10 Oct 00:15**: only the consent and missed-call logs were kept; the Team test village was re-seeded with unconsented families; Kutelabhatha is to be set up again through the console._wait_minutes` 2 for filming). Console logins: `vamsi` and `varun` (Panchayat Secretary group). Custom domain `jalsakshi.humanslop.in` is waiting on DNS validation in Cloudflare._

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
| First real call (answer → digits → reply → hangup webhook) | Claude + Vamsi | **done 8 Oct 21:35** via a spike Lambda; next: redeploy with `-c voice_provider=vobiz` and run the real stack loop (done 9 Oct, see below) |
| Cognito users in role groups; console against the stage | Varun | todo | `admin-create-user` + `admin-add-user-to-group`; build web with stack outputs, redeploy Web stack |
| Context refresh (IMIS HGJ, CGWB groundwater, rain) | Claude | done | India-WRIS times out from AWS, so it falls back to a bundled, labelled CGWB 2025 snapshot (`scripts/snapshot_cgwb.py`) |
| ARCHITECTURE.md contract sync | Varun | todo | Write in the builders' decisions: §4 answered = ANSWERED with a water answer, PARTIAL in VERIFY stays pending, `since`; §5 ESCALATED from every unresolved state and ESCALATED → OPERATOR_FIXED; §6 escalate waits for a fix, one extra verify round, verify targets, ticket id made in CheckInRun; §7 Cedar schema, `policy-evaluation-error`, `calls_today` counts reached DAILY calls; §8 new items (OPENTKT, OP copy, TKT#/META, CALL#…/STEP#, CALL#wait-, CALL#pending-, ACTIVITY#); §10 tools take no arguments; §13 `observed_7d.source`, brief `model_id`, close `409 verification_failed`, brief `403 stale-data`, event kinds UPPERCASE |
| Demo script, filming, edit | both | todo | `docs/DEMO_SCRIPT.md`; film Sat 10:00–18:00 |
| Builder Center blog | Vamsi | todo | separate prize (top 5 blogs) |
| **v2 (Gram Panchayat release), ARCHITECTURE §15** | Claude | **deployed to dev-vamsi 9 Oct 06:35** (1,299 tests; a test pass fixed 14 handler bugs) | Any water source (water points + routing), reconciler r2 per point, IVR self-registration with keypad consent + ledger, press-9 stop (erases the family), missed-call reporting (reject + call-back, Scheduler for out-of-hours), complaint register (numbers, reporters, per-point guards), voice notes → Sarvam STT → agent → complaint, operator reason codes 2-5, sarpanch-approved announcements (Cedar), water-quality tests + official WQMIS record, analytics + weekly summary call (Mon 10:00 IST), public residents' page `/public/villages/{vid}`, runtime TTS cache. Known follow-ups: an operator's "not mine" (key 5) re-routes only at the next notify; a notes-Lambda retry cannot refetch a recording already deleted from Vobiz |
| Real pilot village (Kutelabhatha, LGD 442569) | Vamsi | to set up again after the 10 Oct reset (More → Set up a Panchayat) | Only verifiable records + families' own answers; team phones stay in the "(डेमो)" villages (§15.13). Families: `--families` or `PILOT_FAMILIES` in `.env`, then `--register-calls --allowlist` |
| Missed calls on the DID | Claude | `scripts/vobiz_inbound.py --stage dev-vamsi` | Creates/updates the Vobiz Application (answer URL = `/ivr/vobiz/<token>/inbound`) and attaches the number |
| **First real loop, 9 Oct (Kutelabhatha + demo)** | Claude + Vamsi | partly done | 14:00 consent call failed (Vobiz rejected `finishOnKey=""`, never tested before: the 8 Oct success was the spike Lambda); fixed. 14:15 consent calls: Anamika agreed (house tap → piped scheme); Rahul pressed 9 twice (now treated as a clear no). 14:33 Vamsi's missed call → call-back → complaint #1 opened and assigned in a demo village; the operator call collided with the still-open report call (fixed: 45 s settle wait). Next: operator 'fixed' → confirmation call → closed; Anamika's first 19:00 daily call |
| v2 console pages + residents' page `/v/:vid` | Claude (web build) | **deployed 9 Oct 06:30** at https://jalsakshi.humanslop.in | Village record tabs: overview (government vs families), complaints, water points, families, consent ledger (+CSV), announcements, water quality, analytics. Residents' page needs no login (`?lang=hi`). 144 vitest. UI round: main bundle 155 KB gzip (budget 140: lazy-load new strings), `/api/me` to hide Approve for non-sarpanch, source field on the public view, Hindi official note |
| **Heads-up: console v3 redesign (`docs/DESIGN.md`, Varun's `web/`)** | Claude (WP0 Foundation) | **kickoff + foundation done 9 Oct** | Warm tokens, `ui/`, `shared/`, `shell/`, full §2 route table + legacy redirects, `getMe()` (mock: `?as=sarpanch`), i18n namespaces. WP1–WP7 now own their `src/features/<area>/` and `src/i18n/messages/<area>.ts` (placeholders until then); `/v/:vid` shows a placeholder until WP6 lands. Old `pages/` and `components/` stay until WP8 deletes them. Main bundle 109 KB gzip |
| **Console v3 integrated (WP8)** | Claude (WP8 Integration) | **done 9 Oct, mock mode checked; not yet deployed** | All WP1–WP7 screens wired. Old `pages/`, `components/`, `global.css`, `watercolour.css`, `i18n/messages.ts`, `lib/verdict.ts`, `lib/reliability.ts` and the legacy `LanguageSwitcher` deleted; `Markdown` moved to `shared/`. typecheck, lint, 431 vitest and build clean; main bundle 130 KB gzip (budget 140). All routes checked at 360px EN and 1280px HI in mock mode: no page side-scroll, no white surfaces. Still to do: axe/keyboard pass, real loop on a deployed stage, Vamsi's Hindi review, rename button names in `DEMO_SCRIPT.md`/`FILMING_CHECKLIST.md` |
| **Console v5 + onboarding (simple, English only)** | Claude | **deployed 9 Oct night** | 4 text tabs, no icons, warm palette; first-time setup; families added by pasting numbers, a register photo (Bedrock reads name, mobile, area; the secretary checks before adding) or a missed call (call-back → consent → language → name + mohalla, read by Bedrock). Admin page creates Panchayat logins and per-village settings. Residents' page `/v/:vid` stays bilingual. 38 vitest |
| **Call languages + voice** | Claude | **deployed 9 Oct night** | Per-village call languages chosen by the secretary (first = default) and a per-family choice on the first call. `prompts/hi.yaml` (v3) and `prompts/hne.yaml` (Chhattisgarhi **draft, needs a native speaker's review**), Sarvam Bulbul v3 voice `ritu`. More languages: add `prompts/<code>.yaml` and render |
| **README + "How JalSakshi works" page** | Claude | **done 10 Oct, live** | README rewritten for v2–v5 (features, architecture, cost estimate per village, honest limits). Public page `/how` lists each step and the AWS service behind it, for the video |

### Renamed in the console (v3)
| Old | New |
|---|---|
| Repair ticket | Complaint |
| Households | Families |
| Consent ledger | Consent record (Families › Consent record tab) |
| Water points | Water sources |
| Run check-in now | Call families now |
| Open village record / village tabs | Home "Today" plus sidebar sections |
| Phone simulator | Test call (demo villages only) |
| Gram Sabha brief | Gram Sabha sheet (Reports) |
| quorum | Families needed to confirm |
| Not confirmed (UNVERIFIED day) | Not enough answers |

## Decisions log
- 2026-10-10 05:00: **launch framing.** jalsakshi.humanslop.in (`dev-vamsi`) is the launch site. Kutelabhatha's first users are the team and 5–8 college friends on their own phones (families, pump operator, Sarpanch) at the water pump they use near the IIT Bhilai campus; no demo/test/sample labels. Team test village deleted; Test call hidden from the menu. The 48-hour escalation now calls the real Sarpanch (reason `no_fix_48h`) instead of a simulated PHED; every escalation carries a `reason` (operator, no_fix_48h, panchayat_office) that the Sarpanch hears.
- 2026-10-10 03:45: next-step advice chain is Jev → OpenAI Decisions (`gpt-6-luna`) → fixed rules; a model below 40% confidence or failing is skipped and named on the page. SSM `openai_api_key` (optional, from `.env` `OPENAI_API_KEY` via `put_secrets.py`).
- 2026-10-10 03:00: Claude Haiku 5.5 (`global.` profile) is the first model: about a tenth of Haiku 4.5's per-token price and 4.5 will be retired; India-only routing is not a requirement. Haiku 4.5 (`in.`) and Nova 2 Lite stay as fallbacks. 5.x models get no `temperature` and +1024 tokens for their reasoning.
- 2026-10-10 02:30: operator call keys 6 (say another reason) and 7 (cannot fix alone → Sarpanch gets an `ALERT` call with the operator's words; pressing 1 is logged). AI advice on each complaint: Bedrock overview + suggested next step from TypeSafe Jev (de-identified facts only; SSM `jev_api_key`, optional) or fixed rules; the secretary presses the button. Prompts: `operator.q_fixed` changed, new `operator.q_note/ack_note/ack_panchayat`, `alert.greet/bye` (hi + hne draft). Haiku 5.5 rejects `temperature`: the readers omit it for 5.x models.
- 2026-10-10 01:15: one-call-a-day rule removed (team decision); missed-call cooldown 10 → 2 min and repeat rings now shown in the feed; Families → "Call again" for families still waiting. Fixed: "Call families now" crashed because the PolicyCheck Lambda could not read the SSM allowlist (granted; the lookup is now fail-safe). `DEMO_SCRIPT.md`/`FILMING_CHECKLIST.md` still show a `one-call-per-day` deny beat: drop it when filming.
- 2026-10-10 00:15: stage reset after a team phone heard the Chhattisgarhi complaint menu with no consent step (it had been seeded as already agreed). Test families now start unconsented (`seed_team_test.py`, `--consented` to skip).
- 2026-10-09 night: calling-hours rule removed (calls at any hour; other Cedar rules stay). Console English only; the JalSakshi team creates Panchayat logins and localises each village (public sign-up off). Call language per village + per family; voice Sarvam `ritu`. Register-photo and missed-call onboarding.
- 2026-10-09 evening: simple v4 console (4 text tabs, no icons, 3-step setup), self sign-up, open dialing on dev-vamsi, night call-backs allowed, stage reset (consent + missed-call logs kept), labelled sample village for history; real families re-added through setup from 10 Oct.
- 2026-10-09: v2: JalSakshi is source-agnostic (house tap, standpost, handpump, borewell/well, tanker); JJM data is labelled context only. Consent is a keypad answer on the call plus an append-only ledger (DPDP-standard, Act in force May 2027); no consent audio. Team phones never answer for a real village.
- 2026-10-08: Track = Heat & Water; idea = JalSakshi (household-verified JJM tap supply in Chhattisgarh). Rejected: campus solar (no data access), Chhattisgarh stubble fires (out of season, crowded track; reused for the blog), tanker verification (summer only).
- 2026-10-08: Demo roles are acted and labelled; PHED side simulated and labelled.
- 2026-10-08: Calls go through a Vobiz DID with our Lambda serving the IVR, so call logic lives on AWS. Bolna is the fallback, and the web simulator is the last resort.
