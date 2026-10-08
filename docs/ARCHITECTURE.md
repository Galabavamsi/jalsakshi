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
4. **Verify.** When the operator reports "fixed" (keypad on their call, or the console), the system does **not** trust it. It calls the same households back, and the ticket reaches `CLOSED_VERIFIED` only when a quorum confirms water. Any household saying no sends it to `REOPENED`. A ticket with no fix after 48 h, or no quorum after two verification rounds, escalates to PHED. The PHED side is **simulated and labelled**, and an escalated repair is still verified by households.
5. **Evidence.** For each village and period, a Hindi sheet for the Gram Sabha: observed reliability against the village's *claimed* Har Ghar Jal status, with every number cited.

## 2. Components

| Module | Path | Owner | What it does |
|---|---|---|---|
| core | `src/jalsakshi/core/` | Varun | Domain models (pydantic), reconciler, verification, ticket state machine, IST clock, ids. Pure Python with no AWS imports. |
| policy | `src/jalsakshi/policy/` | Varun | Cedar policies and schema (`policies/jalsakshi.cedar`, `jalsakshi.cedarschema`) plus a thin, fail-closed `cedarpy` wrapper. Each deny returns a plain-language reason (Hindi + English). |
| store | `src/jalsakshi/store/` | Varun | DynamoDB repository (single table) with conditional writes, transactions and an optimistic lock on tickets. |
| voice | `src/jalsakshi/voice/` | Vamsi | IVR flow engine (provider-agnostic), Vobiz XML adapter, web-phone simulator adapter, Hindi prompt catalog. No Bolna adapter is built. |
| agent | `src/jalsakshi/agent/` | Vamsi | Strands agents on Bedrock: (a) spoken note → structured issue, (b) Gram Sabha brief writer. Model factory with fallback chain, then a deterministic template. |
| data | `src/jalsakshi/data/` | Vamsi | Fetchers for JJM IMIS Har Ghar Jal, CGWB 2025 groundwater (India-WRIS, with a bundled snapshot fallback) and Open-Meteo. Each reading carries a `SourceTag`. |
| handlers | `src/jalsakshi/handlers/` | both | Lambda entrypoints only: thin glue that calls the modules above. |
| infra | `infra/` | Varun | AWS CDK (Python) app: Data, Web, App and Obs stacks, Step Functions definitions (`workflows.py`), dashboard. |
| web | `web/` | Varun | Operator console: React, Vite, TypeScript, Cognito auth. |
| prompts | `prompts/` | Vamsi | Hindi prompt text (`hi.yaml`) plus the script that renders it to audio with Sarvam Bulbul and uploads it to S3. |

**Rule:** decisions live in `core`/`policy` (deterministic and tested); language lives in `agent`; I/O lives in `store`/`voice`/`data`. Handlers hold no business logic.

## 3. Domain model (`core/models.py`)

```python
Village      id, name, block, district, imis_village_code?, claimed_hgj: bool?, hgj_certified: bool?,
             claimed_source: SourceTag?, checkin_local_time ("10:30"), quorum: int = 2, active
Household    id, village_id, phone_e164, display_name?, language ("hi"), call_window ("09:00-20:00"),
             consent: Consent{given_at, channel ("voice"|"in_person"), evidence_ref?}? (none = never called), active
Operator     id, role (NAL_JAL_MITRA | SARPANCH | PANCHAYAT_SECRETARY | PHED_AE_SIM | PHED_EE_SIM),
             phone_e164, display_name?, village_ids[]
CheckIn      village_id, date (IST), household_id, attempt, call_id, purpose (DAILY | VERIFY),
             outcome (ANSWERED | UNREACHABLE | DECLINED),
             water (YES | NO | PARTIAL | None), hours (0-24 | None), clean (YES | NO | None),
             note_transcript?, note_issue? (from agent), captured_via (DTMF | SPEECH | SIMULATOR), captured_at
DayStatus    village_id, date, status, counts{answered, yes, no, partial, dirty, unreachable},
             rule_version, computed_at
Ticket       id, village_id, reason (NO_SUPPLY | DIRTY), state, opened_at, updated_at, events[TicketEvent]
TicketEvent  at, actor, kind, from_state?, to_state?, detail{}
SourceTag    source, observed_at?, fetched_at, url?,
             freshness ("live" | "daily" | "annual" | "model" | "simulated" | "replay")
```

`Purpose` also has `OPERATOR`, used only for the operator's call (it never produces a CheckIn).

## 4. Reconciler rules (`core/reconcile.py`, `RULE_VERSION = "r1"`)

Inputs are all CheckIns for (village, date, purpose=DAILY), taking the **latest attempt per household** (latest date, then highest attempt, with a deterministic tie-break). A household counts as **answered** only when that attempt is `ANSWERED` **and** has a water answer: a picked-up call that left the water question blank is not evidence. `UNREACHABLE` and `DECLINED` never count as yes. `dirty` counts answered households with clean = NO.

| Condition (evaluated top to bottom) | Status |
|---|---|
| answered < quorum | `UNVERIFIED` |
| no ≥ quorum **and** no ≥ yes + partial | `NO_SUPPLY` |
| dirty (clean = NO) ≥ quorum | `DIRTY` |
| no + partial ≥ 1 | `PARTIAL` |
| otherwise | `SUPPLIED` |

Opening a ticket: `NO_SUPPLY` or `DIRTY` opens one, but only if no open ticket exists for that village (conditional write on the `OPENTKT` guard, §8). If a ticket is already open, a new bad day adds a `NOTE` event (`detail.note = "day_still_bad"`) instead.

Verification (`core/verify.py`): uses CheckIns with purpose=VERIFY captured at or after `since`, the time of the ticket's latest `VERIFY_STARTED` event, so a NO from an earlier round cannot reopen a ticket that was fixed again. It takes the latest attempt per household with the same "answered" rule. Any `no` gives `REOPENED`; otherwise `yes ≥ quorum` gives `CLOSED_VERIFIED` (Cedar must agree, §7); otherwise the result is `PENDING` and the ticket stays in `VERIFYING`. `PARTIAL` neither confirms nor reopens, so it stays pending.

Property tests (hypothesis): a quorum is never reached by unreachable households; adding a NO answer never improves the status; the result is the same in any order (permutation-invariant); replaying the same webhook is idempotent.

## 5. Ticket state machine (`core/tickets.py`)

```
OPEN ─NOTIFIED─▶ ASSIGNED ─OPERATOR_FIXED─▶ OPERATOR_REPORTED_FIXED ─VERIFY_STARTED─▶ VERIFYING
VERIFYING ─VERIFIED_OK (quorum yes)─▶ CLOSED_VERIFIED
VERIFYING ─VERIFY_FAILED (any no)───▶ REOPENED ─NOTIFIED─▶ ASSIGNED
every unresolved state ─ESCALATED─▶ ESCALATED   (OPEN, ASSIGNED, OPERATOR_REPORTED_FIXED, VERIFYING,
                                                 REOPENED; to PHED_AE_SIM, labelled simulated)
ESCALATED ─OPERATOR_FIXED─▶ OPERATOR_REPORTED_FIXED   (an escalated repair is still verified)
NOTE is allowed in every state and never changes it.
```

Transitions are a pure function `transition(ticket, kind, actor, at, detail) -> Ticket | Denied`. Every event needs an actor and a time no earlier than `updated_at`, and is appended to `events[]` with its from and to states. A ticket counts as open until `CLOSED_VERIFIED`. The pure escalation rule is `needs_escalation` (48 h without a state change; NOTE events do not count). In the deployed stack the TicketFlow heartbeat triggers escalation (§6). Cedar guards the close (§7).

## 6. AWS architecture (all in `ap-south-1`)

```
EventBridge Scheduler (one schedule per village, Asia/Kolkata, written by scripts/seed_demo.py) ──▶ CheckInRun
Step Functions: CheckInRun
   LoadRoster ─▶ Map(households): PolicyCheck (Cedar) ─▶ PlaceCall [waitForTaskToken, 10 min]
              └▶ catch ⇒ MarkUnreachable · not answered ⇒ one retry after 30 min (DAILY only)
   ─▶ ReconcileDay (mints the ticket id when one should open) ─▶ Choice ─▶ StartTicketFlow(ticket_id)
Step Functions: TicketFlow
   OpenTicket ─▶ NotifyOperator (call) [waitForTaskToken: operator "fixed"; heartbeat 48 h ⇒ Escalate]
   ─▶ StartVerification ─▶ Map(verify households) ─▶ EvaluateVerification ─▶ Choice:
        CLOSED_VERIFIED ⇒ done · REOPENED ⇒ NotifyOperator again
        PENDING in round 1 ⇒ wait 30 min, one extra round · PENDING after round 2 ⇒ Escalate
   Escalate (PHED_AE_SIM, simulated) [waitForTaskToken: a fix, 14 days] ─▶ StartVerification
        no fix in 14 days ⇒ Fail (NoFix) ⇒ failed-executions queue (alarmed)
API Gateway HTTP API
   /ivr/vobiz/{token}/{action}  provider webhooks (secret path token from SSM; optional provider CIDR
                                allowlist and Vobiz signature check) ─▶ Lambda ivr
   /api/*              console (Cognito JWT authorizer) ─▶ Lambda api
   /sim/*              web-phone simulator (Cognito) ─▶ Lambda sim ─▶ same IVR engine
Lambda (Python 3.12, Powertools, X-Ray, one shared code asset): one per workflow task, plus api, sim,
   ivr and a daily context refresh (06:00 IST, §11)
DynamoDB (single table, PITR, TTL) · S3: prompt audio behind CloudFront, private evidence bucket
   (today it holds the context/ cache)
Bedrock: in.anthropic.claude-haiku-4-5-20251001-v1:0 → global.amazon.nova-2-lite-v1:0 → template
SSM Parameter Store SecureString /jalsakshi/{stage}/*: vendor keys, ivr_path_token, allowed_numbers
CloudWatch dashboard + alarms (any DLQ > 0: failed executions, scheduler, context refresh; ivr Errors > 0)
CloudFront + S3 for the console · Cognito user pool (operators, one group per role)
```

- **Resuming.** Step Functions resumes with `SendTaskSuccess`. A household call's task token sits on its `CALL#{call_id}` item and is released when the call ends. The fix wait's token sits on `CALL#wait-{tid}`. `POST /api/tickets/{tid}/operator-fixed`, or the operator pressing 1, applies `OPERATOR_FIXED` and releases it. If the fix arrived before the wait began, the task returns at once.
- **Ticket id.** ReconcileDay mints the `tkt_…` id in CheckInRun and passes it to TicketFlow, so a retried OpenTicket replays the same id instead of opening a second ticket.
- **Escalate waits for a fix.** It applies `ESCALATED` (unless the ticket is already escalated) and then waits like NotifyOperator. A fix from the console or the operator call resumes it, and the repair goes through household verification as usual.
- **Verify targets.** These are the households whose latest DAILY answer on the ticket's opening day reported the problem (NO_SUPPLY: water NO or PARTIAL; DIRTY: clean NO). If there are fewer of them than the quorum, every active household is called. The extra round calls only targets that have not answered since `since`. Verify calls get no unreachable retry.
- **Dialling.** Workflow call ids are deterministic, and `STEP#dispatch` is a conditional put, so a retried Lambda never dials twice. The dialler calls only numbers on the stage's `allowed_numbers` consent allowlist. With `voice_provider=simulator`, PlaceCall and NotifyOperator leave the call pending (`CALL#pending-{subject}`) for the console simulator, which resumes the same workflow.
- **Timings** are stage settings: `call_timeout_minutes` 10, `retry_wait_minutes` 30, `escalation_hours` 48, `max_verify_rounds` 2, `fix_timeout_days` 14. A demo stage may shorten escalation with `-c escalation_hours=…`.

## 7. Cedar policies (`policy/policies/*.cedar`)

The policy file permits by default (`@id("allow-by-default")`) and adds one `forbid` per rule, so a deny always names the rule that caused it. The schema (`jalsakshi.cedarschema`) has the entities `System` (the backend), `Operator{role}`, `Household{village_id, consent_given}`, `Village` and `Ticket{village_id, quorum}`. Its actions are `PlaceCall` (context `hour_ist, calls_today, purpose`), `CloseVerified` (`verify_yes`), `ViewHouseholdAnswers` (principal `Operator` only) and `PublishEvidence` (`data_age_hours`, whole hours rounded up). Every request is validated against the schema.

| id | Rule | Shown as (`reason_en`; Hindi in `policy/reasons.py`) |
|---|---|---|
| `consent-required` | forbid `PlaceCall` unless `resource.consent_given` | "No consent on file for this household." |
| `calling-hours` | forbid `PlaceCall` unless 9 ≤ `context.hour_ist` < 21 | "Calls are allowed only between 09:00 and 21:00 IST (TRAI rule)." |
| `one-call-per-day` | forbid `PlaceCall` when `context.calls_today ≥ 1` and purpose = DAILY | "This household was already called today." |
| `verify-needs-quorum` | forbid `CloseVerified` unless `context.verify_yes ≥ resource.quorum` | "Only N of the M households needed have confirmed water." |
| `no-household-view-for-dept` | forbid `ViewHouseholdAnswers` when principal role ∈ {PHED_*_SIM} | "The department sees village totals only, not household answers." |
| `stale-data` | forbid `PublishEvidence` when `context.data_age_hours > 24` | "Data is older than 24 hours. Refresh it first." |
| `policy-evaluation-error` | not a rule: the check could not run (schema mismatch, missing attribute, cedarpy error), so the engine **denies** (fails closed) | "The safety check could not be completed, so this action is blocked." |

- `calls_today` counts today's (IST) DAILY calls that **reached** the household (outcome `ANSWERED` or `DECLINED`). Unreachable attempts do not count, so the 30-minute retry is allowed. VERIFY and OPERATOR calls pass 0.
- Operator calls are checked as `PlaceCall` with the role standing in for consent, so calling hours apply to them too.
- Each deny emits `PolicyDenied{policy_id}` and a `policy_denied` activity entry. The HTTP 403 body uses the first denying rule in policy-file order.

## 8. DynamoDB single table `jalsakshi-{stage}`

| PK | SK | Item |
|---|---|---|
| `VILLAGE#{vid}` | `META` | Village (GSI1PK=`VILLAGES`, GSI1SK=`{vid}`, for listing) |
| `VILLAGE#{vid}` | `HH#{hid}` | Household |
| `VILLAGE#{vid}` | `OP#{oid}` | Copy of an Operator, one per village it serves (lists a village's operators) |
| `VILLAGE#{vid}` | `DAY#{yyyy-mm-dd}` | DayStatus |
| `VILLAGE#{vid}` | `CHK#{date}#{purpose}#{hid}#{attempt:03d}` | CheckIn |
| `VILLAGE#{vid}` | `TKT#{tid}` | Ticket with its events (GSI1PK=`TKTSTATE#{state}`, GSI1SK=`opened_at`; `version_ts` is the optimistic lock) |
| `VILLAGE#{vid}` | `OPENTKT` | Open-ticket guard `{ticket_id, opened_at}`: at most one open ticket per village; deleted when that ticket reaches CLOSED_VERIFIED |
| `TKT#{tid}` | `META` | Pointer `{ticket_id, village_id}` (finds a ticket by id) |
| `TKT#{tid}` | `EVT#{iso_ts}#{seq:04d}` | Ticket event (append-only audit trail) |
| `CALL#{call_id}` | `META` | Call session: the IVR flow state with answers so far, village-day, attempt, provider, task token (TTL 2 days) |
| `CALL#{call_id}` | `STEP#{step}` | Idempotency marker for one IVR step (`dispatch`, `turn-NNN`; TTL 2 days) |
| `CALL#wait-{tid}` | `META` | Task token of the TicketFlow step waiting for a fix (TTL 30 days) |
| `CALL#pending-{hid or oid}` | `META` | Pointer to a workflow call waiting for the console simulator (TTL 1 day) |
| `OP#{oid}` | `META` | Operator |
| `ACTIVITY#{yyyy-mm-dd, UTC}` | `{iso_ts}#{uid}` | Console feed entry (TTL 30 days) |

Idempotency: a CheckIn is a conditional put (written once per attempt). A provider webhook records `(call_id, turn)` as `STEP#turn-NNN` with a conditional put, and a replay repeats the current prompt instead of applying the input twice. Opening a ticket writes the guard, the ticket, the pointer and the first events in one transaction. A ticket save is conditional on `version_ts` and appends the new `EVT#` items (and, on close, deletes the guard) in the same transaction. Reconcile writes `DAY#` with `rule_version` and `computed_at`.

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
- Adapters: `vobiz` (XML response verbs, PSTN via Vobiz DID) and `simulator` (browser keypad in the console that drives the *same* engine; used if PSTN fails on recording day, and labelled as such). No Bolna adapter is built.
- The spoken note is kept as the provider's recording URL on the call. No speech-to-text step is wired into the call path yet.
- Prompt audio: `prompts/hi.yaml` → Sarvam Bulbul (8 kHz) → `s3://…/prompts/hi/{key}.mp3`, served via CloudFront.

## 10. Agent (`agent/`)

- `notes.py`: Strands `Agent` with structured output `NoteIssue{issue: NO_WATER|LOW_PRESSURE|DIRTY|LEAK|OTHER, days_affected?, location_hint?}` from a note transcript. Temperature 0. On error or low confidence it returns `None` (the keypad answers remain the record). It is tested offline but not yet called by any handler (see §9).
- `brief.py`: Strands agent with two read-only tools that **take no arguments**, `village_summary()` and `tickets()`. Both are bound to the one village and period of the request, so the model cannot ask for anything else, and it must read `village_summary` before writing. It writes the Hindi Gram Sabha sheet. **Every number in the text must equal a tool value.** A validator re-parses the numbers. A mismatch, an error or the 24 s deadline (API Gateway stops at 29 s) moves on to the next model, then to the template. Source and freshness labels are added by code, never by the model. The response records `generated_by` and `model_id`.
- `models.py`: factory with an explicit region and model ID (never Strands defaults), timeouts, and the fallback chain from §6.

## 11. Data sources (`data/`)

| Source | Use | Freshness label |
|---|---|---|
| JJM IMIS Har Ghar Jal village report (`ejalshakti.gov.in`, GET) | claimed or certified HGJ counts (state; village where available) | "claimed by state, as on dd/mm" (`daily`) |
| India-WRIS CGWB 2025 (ArcGIS `GWR2025_CGWB` layer 8, `state='CG'`) | block groundwater stage (Durg, Bemetara) | "annual assessment 2025" (`annual`) |
| Open-Meteo forecast (keyless) | rain in the last 7 days at the district HQ (context only) | "model" (`model`) |
| Household check-ins (ours) | observed supply | `live`, or `simulated` when any answer came from the web simulator |

- **CGWB fallback.** India-WRIS times out from AWS. When it fails, the fetcher uses the bundled, dated snapshot `data/snapshots/cgwb_2025_CG.json` (made by `scripts/snapshot_cgwb.py`). Its source reads "…, bundled snapshot" and its `fetched_at` is the snapshot date, so the console labels it as such. The assessment is annual, so the snapshot is not stale.
- **Refresh.** A daily Lambda (06:00 IST) fetches each source once and writes `context/{vid}.json` to the evidence bucket, and the console API reads only that file. A source that fails is `null` and is shown as missing.

## 12. Observability

Powertools logger, metrics and tracer. Metrics: `CallsPlaced`, `CallsAnswered`, `CallsUnreachable`, `DayStatus{status}`, `TicketsOpened`, `TicketsClosedVerified`, `PolicyDenied{policy_id}`, `AgentFallbackUsed`. Dashboard `JalSakshi-{stage}`. Alarms: any DLQ > 0, `Errors` > 0 on the ivr Lambda.

## 13. HTTP API contract (`/api/*` needs a Cognito JWT; JSON bodies are the `core/models.py` types serialised)

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/villages` | – | `[{village: Village, today: DayStatus?, open_ticket: Ticket?, observed_7d: {days, supplied, no_supply, partial, dirty, unverified, source: SourceTag}}]` |
| GET | `/api/villages/{vid}` | – | `{village, households: [HouseholdMasked], operators: [Operator] (phone masked), context: {groundwater: {stage_pct?, category, source: SourceTag}?, rain_7d_mm: {value, source}?, state_hgj: {villages, reported, certified, source}?}}` |
| GET | `/api/villages/{vid}/days` | `?from=YYYY-MM-DD&to=YYYY-MM-DD` (default: last 14 days; at most 92) | `[DayStatus]` |
| GET | `/api/villages/{vid}/checkins` | `?date=YYYY-MM-DD&purpose=DAILY` | `[CheckInMasked]` (CheckIn + `phone_masked` `+91XXXXXX1234`), or `403` `no-household-view-for-dept` for PHED roles |
| POST | `/api/villages/{vid}/checkin/run` | `{purpose: "DAILY"}` | `{execution_arn}`: starts CheckInRun now (demo trigger; each call is still policy-checked). `403` when every household is denied, `409 no_households`, `503 not_configured` |
| GET | `/api/tickets` | `?state=OPEN&village_id=` (every state when `state` is omitted) | `[Ticket]`, newest first |
| GET | `/api/tickets/{tid}` | – | `Ticket` (with events) |
| POST | `/api/tickets/{tid}/operator-fixed` | `{operator_id}` | `Ticket` in OPERATOR_REPORTED_FIXED (the workflow then starts VERIFYING). `404` unknown operator, `422 operator_not_for_village`, `409 transition_denied` |
| POST | `/api/tickets/{tid}/close` | `{}` | `Ticket`; or `403 {denied: true, policy_id: "verify-needs-quorum", reason_hi, reason_en}` when too few households said yes (also noted on the ticket as `NOTE` with `detail.note = "close_denied"`); or `409 verification_failed` when the quorum said yes but a household still says no |
| GET | `/api/villages/{vid}/brief` | `?from&to` (default: last 7 days) | `{markdown_hi, numbers: {...}, generated_by: "agent"\|"template", model_id (null for the template), sources: [SourceTag], generated_at}`, or `403 {denied, policy_id: "stale-data", …}` when the newest DayStatus in the period is over 24 h old or missing |
| GET | `/api/activity` | `?since=iso` (with timezone; default: the last hour) | `[{at, kind, village_id, text_en, text_hi}]`, oldest first, at most 200: live feed for the console |
| POST | `/sim/calls` | `{household_id, purpose}` or `{operator_id, purpose: "OPERATOR"}` | `{call_id, actions: [Action]}`: starts a call through the same engine, or picks up the workflow call pending for that subject |
| POST | `/sim/calls/{call_id}/input` | `{digits?: "2", timeout?: true}` | `{actions: [Action], done: bool}` |
| POST | `/ivr/vobiz/{token}/answer` · `/digits` · `/status` · `/recording` | provider form fields | Vobiz XML |

`Action` = `{type: "play", prompt_key, text_hi, audio_url?} | {type: "get_digits", num_digits, timeout_s, prompts: [...]} | {type: "record", max_s} | {type: "hangup"}`.
`HouseholdMasked` = Household without `phone_e164`, plus `phone_masked`. Errors: `{error: {code, message}}`.
`observed_7d.source.freshness` is `simulated` when any answer in the window came from the web simulator, else `live`.
`TicketEvent.kind` is UPPERCASE: `NOTIFIED`, `OPERATOR_FIXED`, `VERIFY_STARTED`, `VERIFIED_OK`, `VERIFY_FAILED`, `ESCALATED`, `NOTE`. A `NOTE` carries `detail.note` (`day_still_bad`, `close_denied`). Actors are `system:<step>`, `operator:<oid>` (keypad on the operator call) or `console:<user>`.
Activity `kind` is one of `checkin_run`, `call`, `day_status`, `ticket`, `policy_denied`.

## 14. Honest limits (also in the README and the video)

- PHED escalation and the operator's real-world repair are **simulated**. There is no public API into IMIS, Meri Panchayat or PHED.
- Demo villagers and the operator are **team members playing roles**, and this is labelled on screen.
- Outbound calls go only to consenting test numbers. In production this needs a service-series (1600) number and DLT registration via a government or panchayat partner.
- Hindi only in the MVP; Chhattisgarhi speech is handled through keypad-first design.
