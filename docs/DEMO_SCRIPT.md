# Demo script and filming runbook (≤ 3:00)

Judges see only the video, the repo and the writeup. Every claim must be **shown**, AWS must be **visible on screen**, and acted, simulated or demo content must be **labelled on screen**.

This runbook follows what is actually built. It was checked against the code on Fri 9 Oct 2026: `handlers/{api,sim,ivr_vobiz,sfn_tasks,tickets,calls}.py`, `voice/flow.py`, `prompts/hi.yaml`, `policy/policies/jalsakshi.cedar`, `infra/jalsakshi_infra/*.py` and `web/src`. If you change any of these, re-check the shots that use them. Button names are given as the console shows them (Hindi / English).

**Before filming, work through [FILMING_CHECKLIST.md](FILMING_CHECKLIST.md).**

Never show on screen: `.env`, SSM parameters, DynamoDB `HH#` or `OP#` items (they hold real phone numbers), the Vobiz dashboard or the `ivr` Lambda logs (the webhook URL contains the secret path token), or a Cognito password being typed.

---

## 0. Cast, phones and screens

`<stage>` is the stage you film on. CLAUDE.md says to record on `demo` (deployed from `main`); today only `dev-vamsi` is deployed. Either works if the checklist is complete. Example names below use `dev-vamsi`.

| Phone | `TEST_NUMBERS` position | Plays | Ids (नयापारा / अमलीडीह) | Console name |
|---|---|---|---|---|
| **A** | 1st | Household 1 | `hh-nyp-1` / `hh-aml-1` | Demo household 1 |
| **B** | 2nd | Household 2 | `hh-nyp-2` / `hh-aml-2` | Demo household 2 |
| **C** | 3rd | Nal Jal Mitra (pump operator) | `op-nyp-njm` / `op-aml-njm` | Demo Nal Jal Mitra (…) |
| none | – | Household 3: **no consent**, placeholder number, never dialled | `hh-nyp-3` / `hh-aml-3` | Demo household without consent |

- Both demo villages use the same three phones. All calls come from the Vobiz DID listed in HANDOVER.md.
- The PHED AE (simulated) shares phone C's number in the seed, but escalation never dials anyone.
- **Crew (two people is enough).** P1 runs the laptop and OBS and holds phone B. P2 holds phone A, then phone C, on camera. P1 answers B last during verification, *after* clicking **Close ticket**, which is what makes the "1 of 2" deny possible (§3).

**Window 1: JalSakshi console** (CloudFront URL of `<stage>`), signed in as a user in the `PANCHAYAT_SECRETARY` Cognito group (users in no group get that role too). Tab 1 is the village record of **नयापारा (डेमो)**. Tab 2 is **गतिविधि / Activity**, the only page that refreshes itself (every 5 s). Press F5 on every other page to see new state.

**Window 2: AWS console**, region **Asia Pacific (Mumbai) ap-south-1** visible top right. Open these tabs in order:
1. Step Functions → State machines → `jalsakshi-<stage>-checkin-run` → Executions
2. Step Functions → State machines → `jalsakshi-<stage>-ticket-flow` → Executions
3. DynamoDB → Explore items → `jalsakshi-<stage>` → Query: `PK` = `VILLAGE#v-nayapara`, `SK` **Begins with** `DAY#` (do not press Run yet)
4. CloudWatch → Dashboards → `JalSakshi-<stage>` (time range 1 h)
5. Lambda → Functions, filter `jalsakshi-<stage>` (14 functions)
6. EventBridge → Scheduler → Schedules, group `jalsakshi-<stage>-checkins` (only if schedules exist, see §5)

---

## 1. The cut at a glance (2:55 + end card)

| Time | Segment | Shot | Label on screen |
|---|---|---|---|
| 0:00–0:20 | **Problem (20 s)** | 1.1 empty tap · 1.2 IMIS card | *Dramatization: team members* · *Source: JJM IMIS, as on 07/10/2026* |
| 0:20–1:30 | **Flow, part 1 (70 s)** | 2.1 village board · 2.2 Run check-in · 2.3 household calls + consent skip · 2.4 NO_SUPPLY · 2.5 operator call · 2.6 verification calls start | *Demo data* · *Real call, roles acted* · *Repair acted, time compressed* |
| 1:30–1:50 | **Failure case (20 s)** | 3.1 household 1 confirms · 3.2 **Close ticket → Cedar deny "1 of 2"** | *Real Cedar decision* |
| 1:50–2:10 | **Flow, part 2 (20 s)** | 4.1 household 2 confirms → CLOSED_VERIFIED · 4.2 Gram Sabha sheet | *AI-written (Amazon Bedrock), numbers checked* |
| 2:10–2:40 | **Architecture (30 s)** | 5.1 diagram · 5.2 real AWS consoles | – |
| 2:40–2:55 | **Limits (15 s)** | 6.1 text card | – |
| 2:55–3:00 | End card | repo URL | – |

Flow total: 70 s + 20 s = 90 s. The video follows the order things really happened. The deny happens between the two verification answers, so nothing is reordered.

---

## 2. Shot by shot

Prompt text is quoted exactly as in `prompts/hi.yaml` (romanised Hindi, voiced by Sarvam Bulbul). Burn in an English subtitle under each one. You may also show the romanised line, so judges can match it to the repo.

### Segment 1: Problem (0:00–0:20)

**1.1 Empty tap (0:00–0:08).** A team member opens a tap and waits with a bucket; nothing comes out. Film it in advance, anywhere.
- Label: **Dramatization: team members**
- VO: "Almost every home in rural Chhattisgarh now has a tap. Whether water comes out is another question."

**1.2 The claim (0:08–0:20).** Card over your own screenshot of the JJM IMIS Har Ghar Jal report, with its "as on" date visible: **"7,603 villages declared Har Ghar Jal · 6,594 certified · Gram Sabhas decide handovers from 2 Oct"**. Take a fresh screenshot and make the numbers match it.
- Label: **Source: JJM IMIS, as on dd/mm/2026** (the date in your screenshot)
- VO: "The state reports 7,603 villages as Har Ghar Jal, and Gram Sabhas are deciding handovers right now. The official review asks the village committee. Nobody asks the household."

### Segment 2: The loop, part 1 (0:20–1:30)

**2.1 Claim vs. witness (0:20–0:28).** Console, **गाँव / Villages** page.
- On screen: heading *आज नल में पानी आया?* On the **नयापारा (डेमो)** board, *What the state reports*: Declared Har Ghar Jal **Yes**, Certified by Gram Sabha **No**, with the source badge *Demo data: invented village, not an IMIS record*. Next to it, *What households said, last 7 days*: **Water came on 0 of 7 days**, seven empty tiles, and *Today's calls at 10:30 IST*.
- Click **गाँव का पूरा हिसाब / Open village record**.
- Label: **Demo data: invented village (डेमो)**
- VO: "JalSakshi asks them. In this demo village the state claims tap water for all, and the household record is empty."

**2.2 Start the check-in (0:28–0:34).** Village record of नयापारा (डेमो).
- On screen: the header line *"2 households are called daily at 10:30 IST. At least 2 must answer for the day to count."* Under **Registered households (3)**, the third shows *no consent, never called*.
- Click **अभी जाँच कॉल चलाएँ / Run check-in now**. The confirm box says *"This calls 2 households now. Anyone already called today is skipped."* Click **हाँ, कॉल शुरू करें / Yes, start calls** **once**.
- On screen: *"Check-in calls started. Results appear in Activity."* and *Step Functions CheckInRun: arn:aws:states:ap-south-1:…*
- AWS (P1, right after the click): tab 1, newest **Running** execution → Graph view.
- VO, if the stage has the village's schedule (§5): "Each day a check-in run starts at the village's chosen time. Here we start the same run from the console." Without a schedule: "Here we start today's check-in from the console."
- If you film the scheduled run instead (§5, schedules), replace this shot with the EventBridge Scheduler schedule and the execution starting at 10:30, and say "At 10:30 the Scheduler starts the run".

**2.3 Household calls (0:34–0:56).** Split screen: **phone A camera | Step Functions `checkin-run` graph** (`CallHouseholds` Map in progress, `PlaceCall` waiting for the callback). Phones A and B ring together. B is answered off camera, with the same keys.

| Heard (key in hi.yaml) | Text | Subtitle | Key |
|---|---|---|---|
| `household.greet` | "Namaste. JalSakshi se bol rahe hain. Aapke gaon ke nal ke paani ke baare mein teen chhote sawaal hain." | Hello, this is JalSakshi. Three short questions about your village's tap water. | – |
| `household.q_water` | "Aaj nal mein paani aaya? Haan ke liye ek, nahi ke liye do, thoda sa aaya to teen dabaiye." | Did tap water come today? Press 1 for yes, 2 for no, 3 if only a little came. | **2** |
| `household.q_note` (then a beep) | "Kuch aur batana ho to beep ke baad pandrah second bolein. Nahi to hash dabaiye." | To add anything, speak for 15 seconds after the beep. Otherwise press #. | **#** |
| `household.bye` | "Dhanyavaad. Aapka jawab gaon ki Gram Sabha tak pahunchega." | Thank you. Your answer will reach the village Gram Sabha. | hang up after this |

- Press **2**, never 1 or 3. Pressing 1 or 3 adds two more questions (`q_hours`, `q_clean`), the day will not be `NO_SUPPLY`, no ticket opens, and the take for this village is lost for the day.
- You may cut the `q_note` prompt with a visible jump cut.
- **Consent inset (0:50–0:56).** In the graph, click the `CallHouseholds` Map state and choose iteration **index 2** (`hh-nyp-3`; the order is household 1, 2, 3). The path is `PolicyCheck → Allowed → CallSkipped`. Select `PolicyCheck` → Output and show `"policy": {"allowed": false, "policy_id": "consent-required", "reason_en": "No consent on file for this household.", …}`. The Activity tab has the same line: *Policy consent-required blocked call to household hh-nyp-3: No consent on file for this household.*
- Labels: **Real phone call (Vobiz Indian number) · household played by a team member on a consenting test phone**; on the inset, **Cedar: no consent on file, so never called**
- VO (over the inset): "Step Functions calls every registered household, except one with no consent on file. Cedar blocks that call."

**2.4 The day is decided (0:56–1:06).** Split screen: **Step Functions graph** (`ReconcileDay → NeedsTicket → StartTicketFlow → TicketFlowStarted`, all green) | **DynamoDB tab 3, press Run**. Item `SK` = `DAY#2026-10-10` (today's IST date): `status` **NO_SUPPLY**, `counts` `{answered: 2, yes: 0, no: 2, partial: 0, dirty: 0, unreachable: 0}`, `rule_version` **r1**.
- Optional 2 s: query `SK` begins with `CHK#2026-10-10#DAILY#` and show the two check-ins, each with `water: NO`, `outcome: ANSWERED`, `captured_via: DTMF`. These items carry no phone numbers.
- Optional 2 s: console village record after F5. Today's cell in the 14-day strip reads *आज · नहीं*, and the day panel says *"Decided by rule r1; no AI involved."*
- VO: "Both households said no water. A tested rule, not an AI, marks the day NO SUPPLY in DynamoDB and opens a repair ticket."

**2.5 Operator call (1:06–1:22).** Split screen: **phone C camera | Step Functions tab 2**, newest Running execution of `ticket-flow`, waiting at `NotifyOperator`. Phone C rings shortly after both household calls end.

| Heard | Text | Subtitle | Key |
|---|---|---|---|
| `operator.greet` | "Namaste. JalSakshi se Nal Jal Mitra ke liye soochna hai." | Hello. A notice from JalSakshi for the Nal Jal Mitra. | – |
| `operator.summary_no_supply.n2` | "Aaj gaon mein nal mein paani na aane ki shikayat hai. Shikayat karne wale gharon ki sankhya: do." | Complaint today: tap water did not come in the village. Households complaining: two. | – |
| `operator.q_fixed` | "Agar samasya theek ho gayi hai to ek dabaiye. Abhi nahi to do dabaiye." | If the problem is fixed, press 1. If not yet, press 2. | **1** |
| `operator.ack_fixed` | "Dhanyavaad. Hum gharon se pushti karenge, phir shikayat band hogi." | Thank you. We will confirm with the households; then the complaint will close. | hang up after this |

- Do not press 2 on camera. `operator.ack_pending` promises a call "kal" (tomorrow) that the workflow does not make (see FILMING_CHECKLIST, open issues).
- Labels: **Nal Jal Mitra played by a team member · repair acted, time compressed**
- VO: "The pump operator, the Nal Jal Mitra, gets a Hindi summary on his keypad phone, and reports it fixed."

**2.6 Not on his word alone (1:22–1:30).** Console **ticket page** (P1 opened it while phone C was ringing; see §3). Press F5: the progress bar is at **पुष्टि / Checking** and the badge reads *Checking with households*. Step Functions: `StartVerification → CallBackHouseholds` running. Phones A and B ring again.
- VO: "His word is not enough. JalSakshi calls the same households back."

### Segment 3: Failure case (1:30–1:50)

**3.1 Household 1 confirms (1:30–1:38).** Phone A camera.

| Heard | Text | Subtitle | Key |
|---|---|---|---|
| `verify.greet` | "Namaste. JalSakshi se bol rahe hain. Aapne bataya tha ki nal mein paani nahi aa raha tha." | Hello, this is JalSakshi. You told us tap water was not coming. | – |
| `verify.q_water` | "Kya ab nal mein paani aa raha hai? Haan ke liye ek, nahi ke liye do dabaiye." | Is tap water coming now? Press 1 for yes, 2 for no. | **1** |
| `verify.bye` | "Dhanyavaad. Aapki pushti ke bina shikayat band nahi hogi." | Thank you. The complaint will not close without your confirmation. | – |

**3.2 Cedar deny (1:38–1:50).** Console ticket page, full screen. Phone B is **still ringing and unanswered**. Click **शिकायत बंद करें / Close ticket**.
- On screen, a red panel: **नियम ने रोका / Blocked by policy**, *"पानी आने की पुष्टि जरूरी 2 में से सिर्फ़ 1 घरों ने की है।"*, *"Only 1 of the 2 households needed have confirmed water."*, and *Cedar नियम (policy): `verify-needs-quorum`*. The history gains **बंद करने से नियम ने रोका / Close blocked by policy**.
- Label: **Real Cedar policy decision**
- VO: "So can an official close the ticket now? No. Cedar, an open-source policy engine, blocks it: only one of the two households has confirmed water."

### Segment 4: The loop, part 2 (1:50–2:10)

**4.1 Verified (1:50–1:58).** P1 answers phone B: same prompts as 3.1, then presses **1**. Step Functions: `EvaluateVerification → VerifyOutcome → ClosedVerified`, green. Console: F5 on the ticket page shows the stamp **सत्यापित · घरों की पुष्टि से बंद · Closed on households' word**, and all five progress steps are done.
- VO: "The second household confirms. Now, and only now, the ticket closes as verified."

**4.2 Gram Sabha evidence sheet (1:58–2:10).** Village record → **ग्राम सभा पत्र / Gram Sabha brief**. Generating can take up to ~25 s, so cut the wait.
- On screen: **ग्राम सभा साक्ष्य पत्र / Gram Sabha evidence sheet**. Show the line *"Written by the AI agent (Amazon Bedrock, in.anthropic.claude-haiku-4-5-20251001-v1:0); every number was checked against the data"*, scroll the Hindi sheet, and end on the **स्रोत / Sources** list with its freshness badges.
- If the line says *"Built from the fixed template"* instead, Bedrock was not used for this sheet. Either reload and get an agent-written sheet, or keep the take and change the label and VO to "template". Never narrate Bedrock over a template sheet.
- Label: **Hindi sheet written by an AI agent (Amazon Bedrock); every number is checked against stored data**
- VO: "For the Gram Sabha, a Strands agent on Amazon Bedrock, using the India inference profile, writes a Hindi evidence sheet. Every number is checked against the data and cited."

### Segment 5: Architecture (2:10–2:40)

**5.1 Diagram (2:10–2:25).** The architecture diagram (README mermaid, rendered or redrawn).
**5.2 Real consoles (2:25–2:40), about 3 s each.** Step Functions state machines list (2 machines) → Lambda functions filtered `jalsakshi-<stage>` (14) → CloudWatch dashboard `JalSakshi-<stage>` (*Calls*, *Day status*, *Tickets*, *Cedar denies by policy*) → `src/jalsakshi/policy/policies/jalsakshi.cedar` in the editor (six `forbid` rules) → EventBridge Scheduler schedule `checkin-v-nayapara`, `cron(30 10 * * ? *)` Asia/Kolkata (only if it exists).
- Film the dashboard **at least 5 minutes after the take**, because metrics arrive late. Show the *Dead-letter queues* widget and say "zero" only if it really is 0 (rehearsal failures stay in the queue for 14 days).
- VO: "Everything runs in the Mumbai region. EventBridge Scheduler starts a Step Functions run per village. Lambda serves our own Hindi phone menu over a Vobiz number, with prompts voiced by Sarvam and served from CloudFront. DynamoDB keeps every answer and ticket. Cedar enforces consent, calling hours, one call a day and quorum before close. Bedrock writes the brief, CloudWatch watches it all, and CDK deploys it."
- If no schedule exists on the stage, drop "EventBridge Scheduler starts a Step Functions run per village" and say "a scheduled Step Functions run checks in with each village".

### Segment 6: Limits (2:40–2:55) and end card (2:55–3:00)

**6.1 Text card:**
- Demo villages. Villagers and pump operator are our team, on consenting test phones.
- PHED escalation is simulated. There is no IMIS, PHED or Meri Panchayat integration, and we never dial helplines.
- Spoken notes are recorded but not transcribed in this build; the keypad answers are the record.
- Groundwater context uses a bundled CGWB 2025 snapshot (India-WRIS times out from AWS).
- Production calling needs a 1600-series number and DLT registration through a panchayat partner. Hindi only, keypad-first.
- Next: the same rails for summer tanker trips and heat alerts.
- VO: "The calls, workflows and rules you saw are real. The villages are demo data, the villagers and operator are our team, and PHED escalation is simulated. Next summer: the same rails for tanker trips and heat alerts."

**End card:** JalSakshi · जल साक्षी · repo URL · "Built on AWS, ap-south-1".

---

## 3. The live sequence (one continuous real run, about 4 minutes)

The whole loop is one CheckInRun plus one TicketFlow, filmed in real time. Times are rough; the first run of the day is slower because of Lambda cold starts.

1. **T-2 min.** OBS recording. Console on the नयापारा village record; AWS window on tab 1. Phones A, B, C on the table, unlocked, ringer up.
2. **T0.** P1 clicks **Run check-in now → Yes, start calls** (once). P1 switches to AWS tab 1, refreshes the Executions list and opens the newest Running execution in Graph view.
3. **About T+10–30 s.** Phones A and B ring. **Answer within 40 s**, because Vobiz stops ringing at 45 s. P2 answers A on camera and P1 answers B. Each listens to the question, presses **2**, presses **#** after the beep, and waits for *"Dhanyavaad…"* before hanging up. Activity shows *Household hh-nyp-1 answered the DAILY call (water: NO)*.
4. **About T+1 min.** The CheckInRun turns green through `TicketFlowStarted`. P1 presses Run on DynamoDB tab 3 to show `DAY#… NO_SUPPLY`, then opens AWS tab 2, refreshes, and opens the newest Running `ticket-flow` execution (at `NotifyOperator`).
5. **About T+1–1.5 min.** Phone C rings. P2 moves the camera to C and answers.
   - **Safety shot, while C is ringing or the summary plays.** P1 opens the ticket: Villages page, F5, the board's **खुली शिकायत / Open ticket: No water** link. Click **Close ticket**. Expect *"Only 0 of the 2 households needed have confirmed water."* (`verify-needs-quorum`). This is your fallback for 3.2 if the hero shot fails. Click **ठीक है / Dismiss**.
   - P2 presses **1** after `operator.q_fixed`, and hangs up after `ack_fixed`.
6. **About T+2 min.** Phones A and B ring (verification). P2 answers **A** at once and presses **1**. **P1 lets B ring.**
7. Right after A's *"Dhanyavaad. Aapki pushti ke bina…"* (Activity: *answered the VERIFY call (water: YES)*), P1 clicks **Close ticket**. Expect the **"Only 1 of the 2"** deny. This is the hero shot 3.2.
8. **Then, still under 45 s from B's first ring,** P1 answers **B** and presses **1**.
9. **About T+3 min.** `ticket-flow` reaches `ClosedVerified`. F5 the ticket page for the stamp. Activity: *Ticket … closed: households confirmed water is back*.
10. **Optional deny, 5 s.** Village record → **Run check-in now → Yes, start calls**. Expect a red panel: *"इस घर को आज पहले ही कॉल हो चुकी है। / This household was already called today."*, `one-call-per-day`. Nothing starts. Do this only after step 3's calls are finished (see §5).
11. **Gram Sabha brief** (shot 4.2).
12. **About T+8 min.** CloudWatch dashboard and the other architecture shots.

If step 7 is late (B already answered), Close will **succeed**, because the quorum is met and that is correct behaviour. Use the safety shot from step 5 for 3.2 and change the VO to "none of the households has confirmed water yet".

---

## 4. Cedar deny moments the system supports

All six rules live in `src/jalsakshi/policy/policies/jalsakshi.cedar`. Every deny is also written to Activity (*Policy <id> blocked …*) and counted on the dashboard's *Cedar denies by policy* widget.

| Rule | How to trigger it | What appears | Risk | Use |
|---|---|---|---|---|
| **verify-needs-quorum** | **Close ticket** on an open ticket before 2 households confirm by phone: in ASSIGNED ("0 of 2") or between the two verification answers ("1 of 2") | Red **Blocked by policy** panel with the Hindi and English reason and `verify-needs-quorum`; timeline note *Close blocked by policy* | "1 of 2" needs the timing in §3 step 7; "0 of 2" is deterministic | **Pick 1 (hero, 3.2)** |
| **consent-required** | Automatic in every check-in run: `hh-nyp-3` / `hh-aml-3` has no consent. Or **Phone simulator** → Household → *Demo household without consent* → **Start call** | Step Functions Map iteration 2 ends at `CallSkipped`, with `PolicyCheck` output `consent-required`; Activity line. The simulator shows the red panel *"इस घर की सहमति दर्ज नहीं है… / No consent on file for this household."* and the phone screen *Blocked by policy* | None; it happens on its own | **Pick 2 (inset in 2.3)** |
| **one-call-per-day** | **Run check-in now → Yes, start calls** again after the take's calls have finished | Red panel *"इस घर को आज पहले ही कॉल हो चुकी है। / This household was already called today."* (`one-call-per-day`); nothing starts | If clicked while the first run's calls are still in progress, a duplicate run starts instead (§5) | Backup panel shot, §3 step 10 |
| **stale-data** | **Gram Sabha brief** for a village with no check-in in the last 24 h (for example अमलीडीह before its first run) | Error box *"अनुरोध पूरा नहीं हुआ। / Data is older than 24 hours. Refresh it first."* (plain error style, no policy id on the page); Activity: *Policy stale-data blocked publishing the brief…* | Weaker visually; the wording says "older than 24 hours" even when there is no data | Optional B-roll |
| **no-household-view-for-dept** | Sign in as a Cognito user in group `PHED_AE_SIM` (or `PHED_EE_SIM`) → village record → pick a day | Counts still show, but the per-household list is replaced by *"अनुरोध पूरा नहीं हुआ। / The department sees village totals only, not household answers."* | Needs a second Cognito user plus sign-out and sign-in (untested so far) | Optional B-roll |
| calling-hours | Any call or **Run check-in now** outside 09:00–21:00 IST | Panel *"Calls are allowed only between 09:00 and 21:00 IST (TRAI rule)."* | Only after 21:00, when nothing else can be filmed | Not in the cut |

**Picks:** `verify-needs-quorum` is the thesis ("repairs count only when households confirm") and gets its own segment. `consent-required` costs 6 s inside the check-in and shows that the system will not call without consent.

---

## 5. Timing gotchas (read before every take)

- **Calls only 09:00–21:00 IST**, for households *and* the operator (Cedar `calling-hours`, checked at each call). A take lasts about 5 minutes, so start the last one by 20:30. The simulator fallback obeys the same hours. Plan: film Sat 10 Oct 10:00–18:00; video locked Sun 11 Oct 16:00; submit by 19:00 (HANDOVER.md).
- **One full take per village per IST day (two per day).** Once a household's DAILY call is answered, `one-call-per-day` blocks it until midnight IST. Unreachable attempts do not count. Rehearse on Friday, use नयापारा for take 1 and अमलीडीह for take 2. Do not use the Phone simulator on the filming villages before the take, because a simulator call counts too.
- **Never start a run twice for the same village within about 10 minutes** (the call timeout). If **Run check-in now** is clicked again before the first calls have finished, nothing has been stored yet, so Cedar allows it. A second execution starts with the same call ids and takes over the callback. The first execution sits in `PlaceCall` for the full 10 minutes, then reconciles the same answers. If the ticket has closed by then, it **opens a second ticket and rings the operator again**; otherwise it adds *Still failing; no duplicate ticket* to the ticket history. Click once.
- **Never start CheckInRun from the Step Functions console** for a village already run today. With every household skipped, `ReconcileDay` re-reads the morning's answers and, if the earlier ticket is already closed, **opens a second ticket and rings the operator again**. The console button is safe because Cedar denies it.
- **Close every ticket before the next take.** An open ticket blocks a new one (`TicketAlreadyOpen`; the timeline only gets *Still failing; no duplicate ticket*). The Villages page must show *No open ticket*.
- **Answer within 40 s** (Vobiz `ring_timeout` is 45 s). An unanswered DAILY call becomes UNREACHABLE and the run **waits 30 minutes** (`retry_wait_minutes`) before retrying, and only then reconciles. An unanswered verification call leaves the round PENDING and also waits 30 minutes. To recover faster on the filming stage, deploy with `-c retry_wait_minutes=2`, and then do not say "30 minutes" anywhere.
- **Keypad timing is unverified on a real Vobiz call** (HANDOVER.md). Each question waits 10 s (`Gather executionTimeout`) and re-asks once with *"Maaf kijiye, samajh nahi aaya. Phir se sunte hain."*. After a second miss the answer is stored as none, and a household with no water answer counts as UNREACHABLE. If the re-prompt plays even though you pressed, press *during* the question; prompts allow barge-in. The `#` note step was never tested on a real call either. If it hangs, just hang up after the beep: the answer is already saved, and the hangup webhook finishes the call.
- **Escalation.** `NotifyOperator` escalates after `escalation_hours` (default 48) to `ESCALATED` (PHED, simulated; nobody is called). Keep 48 for filming. If you deploy with a small value (for example `-c escalation_hours=0.05`, which is 3 minutes) to film escalation, it applies stage-wide and the operator in every take must press 1 within that time. Film escalation as a separate B-roll (operator presses 2, wait, the ticket shows *Escalated to PHED (simulated)*, then **Operator reports fixed**), not in the main cut.
- **Schedules.** `seed_demo.py --schedules` creates ENABLED schedules at 10:30 (नयापारा) and 11:00 (अमलीडीह) IST. On a `vobiz` stage they ring the phones daily and use up that village's take. Either film the 10:30 run as take 1, or **disable both schedules** in EventBridge Scheduler before 10:30. Re-running the seed with `--schedules` re-enables them.
- **The console does not live-update** except Activity. F5 after every event. The Step Functions execution page updates while it runs; use its refresh button if it lags. The DynamoDB page needs **Run** again.
- **Cold starts.** The first run of the day can take 10–30 s before the phones ring. Cut the wait; don't talk over silence.
- **Brief.** It allows up to 24 s for Bedrock, then falls back to the template. Open one brief off camera to warm the API Lambda before the take. It is refused (stale-data) until the village has a check-in from the last 24 h.
- **Dashboard.** Metrics show up a few minutes late, and rehearsal numbers stay. Failed or aborted rehearsal executions put a message in `jalsakshi-<stage>-workflow-failures` that stays for 14 days, so do not claim "DLQ = 0" unless the widget shows 0.
- **Every redeploy must repeat every `-c` flag.** A deploy without `-c voice_provider=vobiz` silently reverts the stage to the simulator.

---

## 6. Fallback plan: simulator mode (labelled)

**When:** the phones do not ring within about 60 s twice, calls connect to silence, or keypad input is not picked up, and there is no time to debug. A good real take on one village plus a labelled simulator take on the other is better than nothing.

**Where:** a stage deployed **without** `-c voice_provider=vobiz` (simulator is the default). Keep a second stage on the simulator so you do not have to redeploy the filming stage mid-day (for example `dev-vamsi` stays on simulator if you film on `demo`). It has its own table, villages and daily limits. Sign in to its console in a separate browser profile before filming. Switching a stage takes a redeploy of about 5–10 minutes, and must never happen while a take is running.

**How it works:** the same CheckInRun and TicketFlow run. Each `PlaceCall` leaves the call **pending**, and the console's **फ़ोन सिम्युलेटर / Phone simulator** picks it up and drives the same IVR engine, playing the same Sarvam clips in the browser. Answers are stored with `captured_via = SIMULATOR`. The console then labels them *(simulator)* and *JalSakshi household check-ins (web-phone simulator)*, with freshness *simulated*.

**Steps, for each call in §3 order:**
1. Wait until Activity shows *Call to household hh-nyp-1 is waiting in the console simulator*. If you start too early, the simulator places a separate console call that does **not** resume the workflow.
2. **Phone simulator** → गाँव / Village **नयापारा (डेमो)** → फ़ोन कौन उठा रहा है / Who answers the phone **घर / Household** → किसका फ़ोन / Whose phone **Demo household 1** → कॉल किस लिए / Call purpose **रोज़ की जाँच / Daily check-in** → **कॉल शुरू करें / Start call** (or the green key).
3. Press **2**, then **#**, on the on-screen keypad or the keyboard. Repeat for Demo household 2.
4. Operator: Who answers the phone **नल जल मित्र / Operator** → Whose phone **Demo Nal Jal Mitra (नयापारा (डेमो))** → **Start call** → press **1**.
5. Verification: Household → **मरम्मत की पुष्टि / Repair check** → Demo household 1 → **Start call** → **1**. Then do the **Close ticket** deny in the other tab. Then Demo household 2 → **1**.
6. Start each simulator call **within 10 minutes** of the workflow placing it, or `PlaceCall` times out and the 30-minute retry starts.

**Shots that change:** replace every phone camera with the Phone simulator page, which shows the keypad, the LCD prompt text and the *Call transcript*. Keep the Step Functions and DynamoDB split screens unchanged; `captured_via` will read `SIMULATOR`.

**Labels and VO:** put **Simulated: web-phone simulator, same IVR engine, no phone call placed** on every simulator shot. Do not say "phone rings" or "real call". The Cedar denies, Step Functions, DynamoDB and Bedrock remain real and can be narrated as such. Never cut simulator footage into a sequence presented as one real phone run.

---

## 7. Edit and upload

- Final cut **≤ 2:58** with burned-in English subtitles for every Hindi prompt, and all labels from §2 on screen while the relevant footage plays.
- AWS must be visible in segments 2–5. Keep the region (Mumbai) readable in at least one shot. The account id appears in ARNs; that is acceptable, but blur it if you prefer.
- Upload to YouTube as **unlisted** (or public), then open the link in a signed-out browser. Put the link in README.md ("Demo video") and the submission.
- Keep the raw recordings of the real take. They are your evidence if a judge asks whether the call was real.
