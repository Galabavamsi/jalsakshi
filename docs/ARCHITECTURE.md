# JalSakshi: architecture

This is the build contract: modules, data, state machines and APIs. If code and this file disagree, fix one of them in the same PR.

## 1. The loop we are proving

```
 schedule ─▶ call households ─▶ reconcile day ─▶ open ticket ─▶ notify Nal Jal Mitra
                                                                      │
       Gram Sabha evidence ◀── CLOSED_VERIFIED ◀── verification calls ◀┘ (operator says "fixed")
```

1. **Check-in.** At a time each village chose (always 09:00–21:00 IST), registered and consenting households get a short Hindi call: did tap water come today, for how many hours, and was it clean? Answers are given on the keypad. A short spoken note is optional.
2. **Reconcile.** A pure, versioned, unit-tested function (no LLM) turns the household answers into the village's status for that day.
3. **Ticket.** `NO_SUPPLY` or `DIRTY` opens a repair ticket and calls the village's Nal Jal Mitra (pump operator) with a Hindi summary.
4. **Verify.** When the operator reports "fixed" (keypad on their call, or the console), the system does **not** trust it. It calls the same households back, and the ticket reaches `CLOSED_VERIFIED` only when a quorum confirms water. Otherwise it goes back to `REOPENED`. Unresolved tickets escalate after 48 h to PHED. The PHED side is **simulated and labelled**.
5. **Evidence.** For each village and period, a Hindi sheet for the Gram Sabha: observed reliability against the village's *claimed* Har Ghar Jal status, with every number cited.

## 2. Components

| Module | Path | Owner | What it does |
|---|---|---|---|
| core | `src/jalsakshi/core/` | Varun | Domain models (pydantic), reconciler, ticket state machine. Pure Python with no AWS imports. |
| policy | `src/jalsakshi/policy/` | Varun | Cedar policies (`policies/*.cedar`) plus a thin `cedarpy` wrapper. Each deny returns a plain-language reason (Hindi + English). |
| store | `src/jalsakshi/store/` | Varun | DynamoDB repository (single table) with conditional writes and idempotency keys. |
| voice | `src/jalsakshi/voice/` | Vamsi | IVR flow engine (provider-agnostic), Vobiz XML adapter, Bolna adapter (fallback), web-phone simulator adapter, Hindi prompt catalog. |
| agent | `src/jalsakshi/agent/` | Vamsi | Strands agents on Bedrock: (a) free-speech note → structured issue, (b) Gram Sabha brief writer. Model factory with fallback chain, then a deterministic template. |
| data | `src/jalsakshi/data/` | Vamsi | Fetchers for JJM IMIS Har Ghar Jal, CGWB 2025 groundwater (India-WRIS) and Open-Meteo. Each reading carries `source`, `observed_at`, `fetched_at` and `freshness`. |
| handlers | `src/jalsakshi/handlers/` | both | Lambda entrypoints only: thin glue that calls the modules above. |
| infra | `infra/` | Varun | AWS CDK (Python) app: stacks, Step Functions definitions, dashboard. |
| web | `web/` | Varun | Operator console: React, Vite, TypeScript, Cognito auth. |
| prompts | `prompts/` | Vamsi | Hindi prompt text (`hi.yaml`) plus the script that renders it to audio with Sarvam Bulbul and uploads it to S3. |

**Rule:** decisions live in `core`/`policy` (deterministic and tested); language lives in `agent`; I/O lives in `store`/`voice`/`data`. Handlers hold no business logic.

## 3. Domain model (`core/models.py`)

```python
Village      id, name, block, district, imis_village_code?, claimed_hgj: bool?, hgj_certified: bool?,
             claimed_source: SourceTag, checkin_local_time ("10:30"), quorum: int = 2, active
Household    id, village_id, phone_e164, display_name?, language ("hi"), call_window ("09:00-20:00"),
             consent: Consent{given_at, channel ("voice"|"in_person"), evidence_ref}, active
Operator     id, role (NAL_JAL_MITRA | SARPANCH | PANCHAYAT_SECRETARY | PHED_AE_SIM | PHED_EE_SIM),
             phone_e164, village_ids[]
CheckIn      village_id, date, household_id, attempt, call_id, purpose (DAILY | VERIFY),
             outcome (ANSWERED | UNREACHABLE | DECLINED),
             water (YES | NO | PARTIAL | None), hours (0-24 | None), clean (YES | NO | None),
             note_transcript?, note_issue? (from agent), captured_via (DTMF | SPEECH | SIMULATOR), captured_at
DayStatus    village_id, date, status, counts{answered, yes, no, partial, dirty, unreachable},
             rule_version, computed_at
Ticket       id, village_id, reason (NO_SUPPLY | DIRTY), state, opened_at, updated_at, events[]
SourceTag    source, observed_at, fetched_at, freshness ("live" | "daily" | "annual" | "simulated" | "replay")
```

## 4. Reconciler rules (`core/reconcile.py`, `RULE_VERSION = "r1"`)

Inputs are all CheckIns for (village, date, purpose=DAILY), taking the **latest attempt per household**. Only `ANSWERED` counts; `UNREACHABLE` and `DECLINED` never count as yes.

| Condition (evaluated top to bottom) | Status |
|---|---|
| answered < quorum | `UNVERIFIED` |
| no ≥ quorum **and** no ≥ yes + partial | `NO_SUPPLY` |
| dirty (clean = NO) ≥ quorum | `DIRTY` |
| no + partial ≥ 1 | `PARTIAL` |
| otherwise | `SUPPLIED` |

Opening a ticket: `NO_SUPPLY` or `DIRTY` opens one, but only if no open ticket exists for that village (conditional write).

Verification (`core/verify.py`): uses CheckIns with purpose=VERIFY after `OPERATOR_REPORTED_FIXED`. `yes ≥ quorum` gives `CLOSED_VERIFIED`; any `no` gives `REOPENED`; otherwise the ticket stays in `VERIFYING` (retry, then escalate).

Property tests (hypothesis): a quorum is never reached by unreachable households; adding a NO answer never improves the status; the result is the same in any order (permutation-invariant); replaying the same webhook is idempotent.

## 5. Ticket state machine (`core/tickets.py`)

```
OPEN ─notify─▶ ASSIGNED ─operator "fixed"─▶ OPERATOR_REPORTED_FIXED ─▶ VERIFYING
VERIFYING ─quorum yes─▶ CLOSED_VERIFIED
VERIFYING ─any no─────▶ REOPENED ─notify─▶ ASSIGNED
ASSIGNED / REOPENED ─48h no progress─▶ ESCALATED (PHED_AE_SIM, labelled simulated)
```

Transitions are a pure function `(ticket, event) -> ticket | Denied`, and Cedar guards the sensitive ones (§7).

## 6. AWS architecture (all in `ap-south-1`)

```
EventBridge Scheduler (per village, Asia/Kolkata) ──▶ Step Functions: CheckInRun
   CheckInRun: Load roster ─▶ Map(households): PolicyCheck ─▶ PlaceCall ─▶ waitForTaskToken(10 min)
              └▶ catch timeout ⇒ UNREACHABLE, one retry after 30 min ─▶ Reconcile ─▶ Choice ─▶ StartTicketFlow
Step Functions: TicketFlow
   OpenTicket ─▶ NotifyOperator(call) ─▶ waitForTaskToken(operator "fixed", heartbeat 48h ⇒ Escalate)
   ─▶ Map(verify households) ─▶ VerifyReconcile ─▶ Choice(CLOSED_VERIFIED | REOPENED ⇒ loop)
API Gateway HTTP API
   /ivr/{provider}/*   provider webhooks (secret path token + provider IP allowlist) ─▶ Lambda ivr
   /api/*              console (Cognito JWT authorizer) ─▶ Lambda api
   /sim/*              web-phone simulator (Cognito) ─▶ same IVR engine
Lambda (Python 3.12, Powertools, one shared code asset; handler per route)
DynamoDB (single table, PITR, TTL on call sessions) · S3 (prompt audio, consented note audio, evidence sheets)
Bedrock: in.anthropic.claude-haiku-4-5-20251001-v1:0 → global.amazon.nova-2-lite-v1:0 → template
SSM Parameter Store SecureString /jalsakshi/{stage}/* for vendor keys · CloudWatch dashboard + alarms (DLQ > 0)
CloudFront + S3 for the console · Cognito user pool (operators)
```

Step Functions resumes from IVR webhooks using `SendTaskSuccess` with the task token stored on the `CALL#` item.

## 7. Cedar policies (`policy/policies/*.cedar`)

| id | Rule | Shown as |
|---|---|---|
| `consent-required` | forbid `PlaceCall` unless `resource.consent_given` | "No consent on file for this household" |
| `calling-hours` | forbid `PlaceCall` unless 9 ≤ `context.hour_ist` < 21 | "Calls only 09:00–21:00 IST (TRAI)" |
| `one-call-per-day` | forbid `PlaceCall` when `context.calls_today ≥ 1` and purpose = DAILY | "Already called today" |
| `verify-needs-quorum` | forbid `CloseVerified` unless `context.verify_yes ≥ resource.quorum` | "Only N of M households confirmed water" |
| `no-household-view-for-dept` | forbid `ViewHouseholdAnswers` when principal role ∈ {PHED_*_SIM} | "Department sees village totals only" |
| `stale-data` | forbid `PublishEvidence` when `context.data_age_hours > 24` | "Data older than 24 h: refresh first" |

## 8. DynamoDB single table `jalsakshi-{stage}`

| PK | SK | Item |
|---|---|---|
| `VILLAGE#{vid}` | `META` | Village |
| `VILLAGE#{vid}` | `HH#{hid}` | Household |
| `VILLAGE#{vid}` | `DAY#{yyyy-mm-dd}` | DayStatus |
| `VILLAGE#{vid}` | `CHK#{date}#{purpose}#{hid}#{attempt}` | CheckIn |
| `VILLAGE#{vid}` | `TKT#{tid}` | Ticket (GSI1PK=`TKTSTATE#{state}`, GSI1SK=`opened_at`) |
| `TKT#{tid}` | `EVT#{iso_ts}` | Ticket event (who, what, evidence ref) |
| `CALL#{call_id}` | `META` | Call session: household, purpose, task token, IVR step, answers so far (TTL 2 days) |
| `OP#{oid}` | `META` | Operator |

Idempotency: provider webhook `(call_id, step)` uses a conditional put. Reconcile writes `DAY#` with `rule_version` and `computed_at`.

## 9. Voice flow (`voice/flow.py`, provider-agnostic)

```
GREET   "Namaste. JalSakshi se bol rahe hain. Aapke gaon ke nal ke paani ke baare mein 3 chhote sawaal."
Q_WATER "Aaj nal mein paani aaya? Haan ke liye 1, nahi ke liye 2, thoda sa aaya to 3 dabaiye."
Q_HOURS (if 1/3) "Kitne ghante paani aaya? 0 se 9 tak number dabaiye."
Q_CLEAN (if 1/3) "Paani saaf tha? Saaf ke liye 1, gandla ke liye 2."
Q_NOTE  (optional) "Kuch aur batana ho to beep ke baad 15 second bolein, ya # dabaiye."
BYE     "Dhanyavaad. Aapka jawab gaon ki Gram Sabha tak pahunchega."
```
- Every step re-prompts once on timeout or invalid input, then moves on. A missing answer is stored as `None`, never guessed.
- The operator call flow is the same, with `OP_SUMMARY` + "theek ho gaya to 1, abhi nahi to 2".
- Adapters: `vobiz` (XML response verbs, PSTN via Vobiz DID), `bolna` (hosted agent + custom-function webhook, fallback), `simulator` (browser keypad in the console that drives the *same* engine; used if PSTN fails on recording day, and labelled as such).
- Prompt audio: `prompts/hi.yaml` → Sarvam Bulbul (8 kHz) → `s3://…/prompts/hi/{key}.mp3`, served via CloudFront.

## 10. Agent (`agent/`)

- `notes.py`: Strands `Agent` with structured output `NoteIssue{issue: NO_WATER|LOW_PRESSURE|DIRTY|LEAK|OTHER, days_affected?, location_hint?}` from a Sarvam STT transcript. Temperature 0. On error or low confidence it returns `None` (the keypad answers remain the record).
- `brief.py`: Strands agent with tools `village_summary(vid, from, to)` and `tickets(vid, from, to)`. It writes the Hindi Gram Sabha sheet. **Every number in the text must equal a tool value.** A validator re-parses the numbers, and any mismatch falls back to the template.
- `models.py`: factory with an explicit region and model ID (never Strands defaults), timeouts, and the fallback chain from §6.

## 11. Data sources (`data/`)

| Source | Use | Freshness label |
|---|---|---|
| JJM IMIS Har Ghar Jal village report (`ejalshakti.gov.in`, GET) | claimed or certified HGJ counts (state; village where available) | "claimed by state, as on dd/mm" |
| India-WRIS CGWB 2025 (ArcGIS layers 6 and 8, `state='CG'`) | block groundwater stage (Durg, Bemetara) | "annual assessment 2025" |
| Open-Meteo forecast (keyless) | rain in the last 7 days (context only) | "model" |
| Household check-ins (ours) | observed supply | "live" |

## 12. Observability

Powertools logger, metrics and tracer. Metrics: `CallsPlaced`, `CallsAnswered`, `CallsUnreachable`, `DayStatus{status}`, `TicketsOpened`, `TicketsClosedVerified`, `PolicyDenied{id}`, `AgentFallbackUsed`. Dashboard `JalSakshi-{stage}`. Alarms: any DLQ > 0, `Errors` > 0 on the ivr Lambda.

## 13. HTTP API contract (`/api/*` needs a Cognito JWT; JSON bodies are the `core/models.py` types serialised)

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/villages` | – | `[{village: Village, today: DayStatus?, open_ticket: Ticket?, observed_7d: {days, supplied, no_supply, partial, dirty, unverified}}]` |
| GET | `/api/villages/{vid}` | – | `{village, households: [HouseholdMasked], operators: [Operator], context: {groundwater: {stage_pct, category, source: SourceTag}?, rain_7d_mm: {value, source}?, state_hgj: {villages, reported, certified, source}?}}` |
| GET | `/api/villages/{vid}/days` | `?from=YYYY-MM-DD&to=YYYY-MM-DD` | `[DayStatus]` |
| GET | `/api/villages/{vid}/checkins` | `?date=YYYY-MM-DD&purpose=DAILY` | `[CheckInMasked]` (household id + answers; phone masked `+91XXXXXX1234`) |
| POST | `/api/villages/{vid}/checkin/run` | `{purpose: "DAILY"}` | `{execution_arn}`: starts CheckInRun now (demo trigger, still policy-checked) |
| GET | `/api/tickets` | `?state=OPEN&village_id=` | `[Ticket]` |
| GET | `/api/tickets/{tid}` | – | `Ticket` (with events) |
| POST | `/api/tickets/{tid}/operator-fixed` | `{operator_id}` | `Ticket` (moves to OPERATOR_REPORTED_FIXED → VERIFYING) |
| POST | `/api/tickets/{tid}/close` | `{}` | `Ticket`, or `403 {denied: true, policy_id, reason_hi, reason_en}` |
| GET | `/api/villages/{vid}/brief` | `?from&to` | `{markdown_hi, numbers: {...}, generated_by: "agent"|"template", sources: [SourceTag], generated_at}` |
| GET | `/api/activity` | `?since=iso` | `[{at, kind, village_id, text_en, text_hi}]`: live feed for the console |
| POST | `/sim/calls` | `{household_id or operator_id, purpose}` | `{call_id, actions: [Action]}`: web-phone simulator starts a call through the same engine |
| POST | `/sim/calls/{call_id}/input` | `{digits?: "2", timeout?: true}` | `{actions: [Action], done: bool}` |
| POST | `/ivr/vobiz/{token}/answer` · `/digits` · `/status` · `/recording` | provider form fields | Vobiz XML |

`Action` = `{type: "play", prompt_key, text_hi, audio_url?} | {type: "get_digits", num_digits, timeout_s, prompts: [...]} | {type: "record", max_s} | {type: "hangup"}`.
`HouseholdMasked` = Household without `phone_e164`, plus `phone_masked`. Errors: `{error: {code, message}}`.

## 14. Honest limits (also in the README and the video)

- PHED escalation and the operator's real-world repair are **simulated**. There is no public API into IMIS, Meri Panchayat or PHED.
- Demo villagers and the operator are **team members playing roles**, and this is labelled on screen.
- Outbound calls go only to consenting test numbers. In production this needs a service-series (1600) number and DLT registration via a government or panchayat partner.
- Hindi only in the MVP; Chhattisgarhi speech is handled through keypad-first design.
