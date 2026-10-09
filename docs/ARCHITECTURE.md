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
   OpenTicket ─▶ SettleBeforeNotify (45 s, so a resident's call-back has ended) ─▶ NotifyOperator (call)
                [waitForTaskToken: operator "fixed"; heartbeat 48 h ⇒ Escalate]
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
Bedrock: global.anthropic.claude-haiku-5-5 → in.anthropic.claude-haiku-4-5-20251001-v1:0 → global.amazon.nova-2-lite-v1:0 → template
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
| ~~`one-call-per-day`~~ | removed by the team on 10 Oct: the secretary may call the families again the same day | n/a |
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

## 15. v2: the Gram Panchayat release (any water source, residents can report)

v2 drops the assumption that every house has a JJM tap. It records **whatever water source each family actually uses**, lets residents **report problems themselves with a missed call**, and gives the Panchayat a **complaint register, announcements, water-quality records and analytics**. Residents get their own view of the same data. Sections 1–13 still apply except where this section changes them.

### 15.1 Water points and how households get water

| Model | Fields |
|---|---|
| `WaterPoint` | `id`, `village_id`, `kind` (`PIPED` \| `HANDPUMP` \| `BOREWELL` \| `TANKER` \| `OTHER`), `name`, `name_hi`, `hamlet?`, `location?` (`GeoPoint{lat, lon, source, accuracy_m?}`), `supply_window?` (`"06:30-08:00"`), `operator_ids[]` (first = primary), `quorum?` (default: the village's), `provisional` (true when it was created by a registration and nobody has checked it yet), `active` |
| `Household` (added) | `access?` (`HOUSE_TAP` \| `STANDPOST` \| `HANDPUMP` \| `BOREWELL` \| `TANKER` \| `OTHER`), `water_point_id?`, `hamlet?`, `registered_via` (`seed` \| `ivr` \| `console`), `consent_status` (`NONE` \| `GRANTED` \| `DECLINED` \| `WITHDRAWN`) |
| `Village` (added) | `name_hi`, `lgd_code?`, `census_code?`, `gram_panchayat?`, `gp_lgd_code?`, `census_households?`, `census_population?`, `location?`, `inbound` (true for the village unknown missed-call numbers register into); `claimed_hgj` is now optional context only |
| `OperatorRole` (added) | `HANDPUMP_MECHANIC` |

- **Access vs point.** `access` is how a family draws water. The water point is the thing that breaks and gets repaired. `HOUSE_TAP` and `STANDPOST` both draw from the village's `PIPED` point, and the other access kinds map to the point of the same kind. Registration attaches the household to the village's only active point of that kind. If there is none, it creates a `provisional` point (for example "Kutelabhatha piped supply") for the secretary to name later.
- **Routing.** A ticket goes to its water point's first operator. If the point has none, it goes to the village's `NAL_JAL_MITRA`, then to its `SARPANCH`.
- **Questions follow the source.** The daily question names the family's own source ("Did water come in your house tap today?", "Did you get water from the handpump today?", "Did the tanker come today?"). The hours question is asked only for `HOUSE_TAP`/`STANDPOST`. A NO answer gets one extra question: where did the family get drinking water instead (1 another tap or handpump, 2 bought it, 3 got none). This is stored as `CheckIn.fallback`.

### 15.2 Reconciler r2 (per water point)

`CheckIn` gains `water_point_id?`, copied from the household when the call is made, and `fallback?`. `RULE_VERSION = "r2"`:

1. Group the day's DAILY and REPORT check-ins by `water_point_id`. A household with no point joins the village-wide group `None`.
2. In each group, take each household's latest answer by `captured_at` (then attempt), and apply the r1 table (§4) with the point's quorum. This gives `PointStatus{water_point_id, status, counts}`.
3. The village status is the worst status among points that have evidence, in the order `NO_SUPPLY` > `DIRTY` > `PARTIAL` > `SUPPLIED`. It is `UNVERIFIED` only when no point has evidence. `DayStatus.points[]` keeps the detail.

A village with one water point gets exactly the r1 result.

### 15.3 Registration and consent (DPDP-standard keypad consent)

- **The REGISTER call.** This is the first call to a family that has not yet consented. It is either seeded or a callback after a missed call from an unknown number.
  - A Hindi notice (`notice_version = "hi-1"`) says who we are, what data we collect, why, who sees it, and that voice notes are transcribed by Sarvam AI. It explains how to stop: press 9 on any call, or give a missed call and press 9.
  - `Q_AGE`: 1 = 18 or older, 2 = under 18.
  - `Q_CONSENT`: 1 agree, 2 hear the notice again (at most twice), 3 decline.
  - `Q_ACCESS`: 1 house tap, 2 public tap, 3 handpump, 4 borewell or well, 5 tanker.
  - Then a confirmation.
  - A timeout or an invalid key never counts as consent.
- **The ledger.** `ConsentEvent` is append-only (`VILLAGE#{vid}` / `CONSENT#{iso}#{hid}`):
  - `household_id`, `phone_masked`, `action` (`GRANTED` \| `DECLINED` \| `WITHDRAWN` \| `MINOR`)
  - `notice_version`, `notice_sha256` (of the notice text), `channel` (`ivr_keypad` \| `in_person` \| `console`)
  - `call_id`, `digits`, `at`
  - No audio is recorded for consent.
  - The console exports the ledger as consent proof. It is labelled "designed to the DPDP Act 2023 / Rules 2025 standard (consent provisions in force May 2027)".
- **Withdrawal.** 9 on any household call, or in the missed-call menu, then 9 again to confirm, appends `WITHDRAWN` to the ledger and **erases the household and its phone lookup**. Check-ins keep only the household id. The ledger keeps only the masked phone. The number is never called again unless it gives a missed call itself, which starts a fresh registration.
- **Cedar** (§7, extended):
  - `Household` gains `consent_status`; `PlaceCall` context gains `caller_initiated: Bool`.
  - `consent-required` now exempts `purpose == "REGISTER"`.
  - New `no-calls-after-withdrawal` forbids any call when `consent_status ∈ {DECLINED, WITHDRAWN}`, unless `caller_initiated`.
  - `one-call-per-day` was removed on 10 Oct (`calls_today` stays in the context for the record).
  - New `callback-limit` forbids caller-initiated calls when `callbacks_today ≥ 5`.

### 15.4 Missed-call reporting

```
resident ──missed call──▶ Vobiz DID ──▶ /ivr/vobiz/{token}/inbound
   reply <Hangup reason="rejected"/>   (the caller is not charged; per Vobiz docs, neither are we)
   log MISSED#{phone}; ignore withheld numbers; rate limit 1 callback / 2 min, 5 / day
   ─▶ EventBridge Scheduler one-off at(+1 min), or 09:00 IST if it arrived outside calling hours
   ─▶ Lambda callback ─▶ Cedar PlaceCall(caller_initiated) ─▶ dial the caller back with:
        consented household   → REPORT menu
        operator (no household) → OPERATOR flow for their oldest open ticket
        anyone else           → REGISTER flow (the household record is created only on consent)
```

- **REPORT menu**:
  - 1 = no water today
  - 2 = dirty water
  - 3 = other complaint: speak after the beep (voice note, §15.6)
  - 4 = hear today's village status and open complaints
  - 9 = stop calls
- **What 1 and 2 do.** They write a `CheckIn(purpose=REPORT)`, which counts in r2, then open or join a complaint ticket (§15.5). The caller hears the complaint number.
- **Allowlist.** On demo stages the dialer still calls only allowlisted numbers. A missed call from any other number is logged (masked) and gets no callback.

### 15.5 Complaint register (tickets v2)

- **Ticket fields.**
  - `Ticket` gains `number`, a per-village sequence (`SEQ#TICKET`, atomic counter). The number is spoken as "shikayat kramank 7".
  - Also `water_point_id?`, `origin` (`reconcile` \| `report` \| `voice_note` \| `console`) and `reporters[]` (household ids).
  - Also `quorum` (households needed to close it) and `issue?` (AI-extracted, §15.6).
  - Also `blocker?` (the operator's latest reason code, §15.7).
- **Reasons.** `TicketReason` adds `LOW_PRESSURE`, `LEAK`, `BROKEN` (pump or handpump) and `OTHER`.
- **Guard.** It is now `OPENTKT#{wpid or "village"}#{reason}`, so there is one open ticket per water point and reason. A second report of the same problem joins the open ticket: it adds the reporter and a `NOTE{note: "another_report"}`.
- **Quorum.**
  - Reconcile-opened tickets use the point's quorum.
  - Report-opened tickets use `min(point quorum, number of reporters)`, so one resident's complaint can be fixed and closed by that resident's own confirmation.
  - Verify targets are the reporters plus the households whose DAILY or REPORT answer showed the problem.
- The state machine (§5), TicketFlow (§6) and the close rule (§7) are unchanged. A report-opened ticket starts the same TicketFlow with a pre-minted id.

### 15.6 Voice notes → issue

```
Record (25 s max, # to end) ─▶ /recording callback ─▶ async Lambda notes
  ─▶ GET recording with Vobiz auth ─▶ s3://evidence/audio/{vid}/{call_id}.{wav|mp3}
     (SSE, lifecycle 365 days) ─▶ DELETE the Vobiz copy
  ─▶ Sarvam STT (saaras:v4, hi-IN, keyterms: nal, tanki, pipe, motor, handpump, ...)
  ─▶ agent/notes.py (Bedrock, temperature 0) ─▶ NoteIssue{issue, summary_hi, summary_en,
     location_hint?, days_affected?, confidence}
  ─▶ stored on the CheckIn (note_transcript, note_issue) and on the ticket
```

- **Which ticket.** In the REPORT menu (option 3), a confident issue opens or joins a ticket with that reason. A low-confidence issue, or an `OTHER` one, opens an `OTHER` ticket for a human to read.
- **Daily-call notes.** A note on a daily call never opens a ticket on its own. It is attached as a `NOTE` to the open ticket, if there is one.
- **Labels.** The console labels the result "AI-transcribed from a resident's voice note, not yet confirmed by the operator". The AI never closes or reopens a ticket.

### 15.7 Operator reason codes

The operator call asks, after the summary: 1 fixed · 2 parts needed · 3 no electricity · 4 pipe broken or leaking · 5 not my responsibility · 6 something else (say it) · 7 cannot fix it alone, needs the Sarpanch.

- 1 applies `OPERATOR_FIXED`, as before.
- 2–7 add a `NOTE{note: "operator_reason", code}` and set `ticket.blocker` (`OTHER` for 6, `NEEDS_PANCHAYAT` for 7).
- Code 5 also moves the ticket to the next person in the routing chain (§15.1).
- 6 and 7 are followed by a spoken note (30 s, `#` ends it). The notes Lambda transcribes it (Sarvam), adds an English gist (Bedrock) and writes `NOTE{note: "operator_voice", transcript, summary_en, code}` on the complaint, labelled AI-transcribed.
- 7 also applies `ESCALATED{to: "SARPANCH", by: operator}` (an already escalated complaint keeps its state) and queues the outbound job `panchayat_alert` 45 s later, so the operator's words are usually transcribed by then. That job calls the village's Sarpanch, or the Panchayat Secretary when there is no Sarpanch, with a new `ALERT` call: intro, the complaint number, problem, place and the operator's words (runtime TTS), then "press 1 if you heard". Pressing 1 writes `NOTE{note: "sarpanch_told"}`. The TicketFlow keeps waiting for a fix; the 48-hour PHED escalation (simulated) still applies.
- Analytics counts blockers per water point. This is the "why does water fail here" evidence.

### 15.8 Approved announcements (broadcasts)

- **The model.** `Broadcast{id, village_id, water_point_id?, kind (SUPPLY_CHANGE | BOIL_WATER | REPAIR_DONE | MEETING | CUSTOM), text_hi, state (DRAFT → APPROVED → SENT | CANCELLED), created_by, approved_by?, sent_at?, recipients, delivered, heard}`.
- **Who can do what.**
  - The secretary (or anyone with a console login) drafts an announcement.
  - Cedar `ApproveBroadcast` allows only `SARPANCH`.
  - Cedar `SendBroadcast` requires `APPROVED`, at most 2 sent per village per 7 days, and calling hours.
  - Each recipient call also passes `PlaceCall` (consent).
- **Delivery.** Each consenting household on the target point, or every household in the village, gets a short call. The announcement is played (Sarvam TTS, cached) and then "press 1 if you heard it, 2 to hear it again". `heard` counts the 1s.

### 15.9 Water quality

- **The model.** `QualityTest{id, village_id, water_point_id, tested_at, method (FTK | LAB), result (SAFE | UNSAFE), parameters{name: value}, entered_by, source: SourceTag}` is recorded from the console.
- **On DIRTY tickets.** A `DIRTY` ticket with no test after it opened shows "test needed". A test result is added to the ticket as a `NOTE`.
- **Official results.** Official JJM WQMIS lab results are shown as separate, labelled context when the village has any.

### 15.10 Analytics and the weekly summary

`core/analytics.py` is pure, deterministic and unit-tested. For a village and period it produces:

- Per water point:
  - days observed, supplied, partial, no supply, dirty and unknown
  - reliability = supplied ÷ observed (unknown days excluded and shown separately)
  - complaints by reason
  - median and worst repair time (`opened_at` → `CLOSED_VERIFIED`)
  - reopen count
  - open tickets and their ages
  - blockers
- Households:
  - registered, consented, withdrawn
  - coverage against the Census households
  - answer rate (answered ÷ called)
  - fallback sources used
- Announcements sent and heard.

Every number carries its `SourceTag`.

- `GET /api/villages/{vid}/analytics?from&to` returns all of it.
- **Weekly summary.** Every Monday at 10:00 IST, EventBridge triggers the `weekly_summary` Lambda. It fills a fixed Hindi template from the analytics, with no LLM involved, and calls the village's `SARPANCH` and `PANCHAYAT_SECRETARY` (purpose `SUMMARY`; the text is played through TTS). The same text is available at `GET /api/villages/{vid}/summary`.

### 15.11 Residents' view (no login)

- **The page.** `GET /public/villages/{vid}` needs no auth and is cached for 60 s. It shows:
  - the village and its codes
  - today's status per water point
  - the last 30 days' statuses
  - open complaints (number, reason, water point, age, state; no names or phones)
  - closed and verified complaints, with the median repair time
  - sent announcements
  - sources
- The same data is spoken in REPORT option 4. The console serves it at `/v/{vid}`; the printable QR poster comes in the UI round.

### 15.12 New keys, purposes and routes

- **Purposes:** `REGISTER`, `REPORT`, `BROADCAST`, `SUMMARY`, `ALERT` (a complaint sent to the Sarpanch, §15.7). Only `REPORT` produces a CheckIn, alongside the existing `DAILY` and `VERIFY`.
- **DynamoDB:**
  - `VILLAGE#{vid}`: `WP#{wpid}` · `CONSENT#{iso}#{hid}` · `BCAST#{bid}` · `QT#{iso}#{qid}` · `SEQ#TICKET`
  - `OPENTKT#{wpid|village}#{reason}`
  - `PHONE#{e164}`: `HH#{hid}` (`village_id`) and `OP#{oid}`, the reverse lookup for inbound calls
  - `MISSED#{e164}`: `{iso}`, a missed-call log (TTL 30 days); `data.callback` records whether that ring queued a call-back, so only those count towards the 2-minute cooldown and the 5-a-day limit
- **Routes:**
  - `POST /ivr/vobiz/{token}/inbound` (the Vobiz Application's answer URL)
  - `GET /public/{proxy+}` (no authorizer)
  - `GET|POST /api/villages/{vid}/water-points`
  - `GET /api/villages/{vid}/consents`
  - `GET|POST /api/villages/{vid}/broadcasts`, `POST /api/villages/{vid}/broadcasts/{bid}/approve|send|cancel`
  - `GET|POST /api/villages/{vid}/quality`
  - `GET /api/villages/{vid}/analytics`, `GET /api/villages/{vid}/summary`
  - `POST /api/villages/{vid}/households/{hid}/consent-call` (call a family that has not answered yet)
  - `GET /api/tickets/{id}/overview`, `POST /api/tickets/{id}/send-to-sarpanch`, `POST /api/tickets/{id}/call-operator` (§15.14)
- **Runtime TTS** (`voice/tts.py`). A `Play` with no pre-rendered clip (a number, a water point name, an announcement) is rendered once with Sarvam Bulbul at request time. It is cached in the prompt bucket under `prompts/hi/dyn/{sha256[:32]}.mp3` and served through CloudFront (`{audio_base_url}/dyn/...`). Vobiz `Speak` has no Hindi voice, so text is never sent to it.

### 15.14 AI advice on a complaint (10 Oct)

The complaint page shows an **AI overview** and a **suggested next step**. Advice only: nothing changes until the secretary presses "Send to the Sarpanch" or "Call the pump operator again", and those actions go through the same state machine, Cedar and dialer as everything else.

- **Facts** (`agent/overview.py: facts_for`): built deterministically from the complaint record. De-identified: the problem, status, hours open, counts, the operator's reason codes and the English gist of the operator's own words with long digit runs removed. Never names, phone numbers, household ids or families' words.
- **Next step** (`suggest`): one of `CALL_OPERATOR_AGAIN`, `SEND_TO_SARPANCH`, `RAISE_WITH_BLOCK_OFFICE` (the secretary does this; JalSakshi never calls government numbers), `WAIT_FOR_REPAIR`.
  - A chain of decision models, each asked one typed `choice` question plus an `urgent` yes/no, one attempt each with a 4 s timeout:
    1. TypeSafe **Jev** (`POST https://api.typesafe.ai/v1/systemone`, model pinned to `jev-1.13.0`, SSM key `jev_api_key`);
    2. **OpenAI Decisions** (`POST https://api.openai.com/v1/decisions`, `gpt-6-luna`, `choice` + `predicate`, SSM key `openai_api_key`);
    3. the **fixed rules** (`suggest_rules`), which are also the behaviour without keys.
  - A model that fails or is below 40% confident is skipped, and the page lists why ("the Jev decision model was unsure (13%)"). Both models are outside AWS, which is why they get the codes and counts only (not even the gist of the operator's words).
  - A test of 8 labelled made-up complaints on 10 Oct: OpenAI 6/8, Jev 5/8 (one timeout), both about 0.4 s from India. The rules match the labels by construction.
- **Overview text**: 2–3 plain sentences from the Bedrock model chain (`agent.reader.converse_text`), with a fixed template as fallback. The page names who wrote it and when, and shows Jev's confidence as a percentage with its source.
- **During the call loop**: after an operator's spoken note (key 6), if the advice is "send it to the Sarpanch", the activity feed says so. The secretary decides.
- Results are cached per Lambda container for each version (`updated_at`) of a complaint.

### 15.13 Pilot honesty rules (real village, real families)

- **Who is seeded.** `scripts/seed_village.py` seeds only verifiable records:
  - Kutelabhatha's LGD/Census master (`data/villages/durg_block.json`);
  - the piped scheme JJM IMIS lists (`wp-piped-1`, scheme 40006378);
  - the pilot coordinator. The coordinator's display name says they stand in for the Panchayat, and complaints are routed to them because the real Nal Jal Mitra is not enrolled.
- **Families.** They are added with consent `NONE` and have no answers. Their first call is the REGISTER (consent) call.
- **Team phones.** These live only in the demo villages (`seed_demo.py`, names marked "(डेमो)", `simulated` source tags). A missed call from a team phone resolves to the demo household, so nothing a team member presses is recorded against Kutelabhatha. `seed_village.py` refuses a team number as a family.
- **Government records.** They are shown next to families' answers and never merged with them: "Government record (JJM IMIS, as on 09 Oct 2026): 450 of 455 households have a tap connection; status In progress". The newest official household tap test is Aug 2023, and the console says so instead of calling the water safe.

## 16. Accounts, first-time setup and real calling (9 Oct evening)

- **Accounts.** A Panchayat secretary creates their own account (Cognito hosted UI, email + password, emailed code). Each account sees only the villages bound to it (`USER#{sub}` / `VILLAGE#{vid}`); the `ADMIN` group (the team) sees all. `GET /api/me` says whether setup is needed.
- **Setup (3 steps).**
  1. Pick the village from the LGD/Census list (`GET /api/places`) or type it in.
  2. Pump operator's and sarpanch's name and mobile number.
  3. Paste families' mobile numbers (`POST /api/villages/{vid}/households/bulk`). Each new family gets **one consent call** (at most 25 waiting per village); families can also join themselves with a missed call (poster).
  - Creating the village also creates its daily 19:00 check-in schedule. The first village on a stage takes unknown missed callers.
- **Who can be dialled.** On an `open_dialing` stage, any number registered in the table can be dialled: a family a signed-in secretary added, a family that gave its own missed call, or a team member. Other stages use only the SSM allowlist. Every call still passes Cedar, and `+910000…` placeholders and helplines are never dialled. A team member's number is never registered as a family.
- **Calling hours.** There is no calling-hours rule (the team removed it on 9 Oct). The daily call goes at the village's chosen time (default 19:00), and missed calls are called back at once. Cedar still enforces consent, no calls after a refusal, and the call-back limit. There is no one-call-a-day rule either (removed 10 Oct): "Call families now" calls every agreed family each time it is pressed, and a family that did not pick up its consent call can be called again from Families → "Call again" (each console request is its own call id; a retried delivery of one request dials once).
- **Fresh start and sample data.** `scripts/reset_stage.py` clears village data but keeps the consent ledger and the missed-call log. `scripts/seed_sample.py` adds a labelled **Sample village** (`sample-…` id, generated answers stored as `SIMULATOR`, `+910000…` numbers). Its 30 days of history are computed by the real reconciler, for showing reports before a real village has history. Real villages never get generated data.

## 14. Honest limits (also in the README and the video)

- PHED escalation and the operator's real-world repair are **simulated**. There is no public API into IMIS, Meri Panchayat or PHED.
- Demo villagers and the operator are **team members playing roles**, and this is labelled on screen.
- Outbound calls go only to consenting test numbers. In production this needs a service-series (1600) number and DLT registration via a government or panchayat partner.
- Hindi only in the MVP; Chhattisgarhi speech is handled through keypad-first design.
