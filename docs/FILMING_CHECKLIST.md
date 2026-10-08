# Filming checklist (print this)

Use this together with [DEMO_SCRIPT.md](DEMO_SCRIPT.md); section numbers (§) refer to that file. `<stage>` is the stage you film on. Run the commands from the repo root unless a step says otherwise. Use `uv run --no-sync` for Python.

## A. The day before (Fri 9 Oct; real calls only 09:00–21:00 IST)

- [ ] **Stages chosen.** Filming stage `<stage>` on `vobiz` (CLAUDE.md: `demo` from `main`; `dev-vamsi` is the one deployed today), plus a **fallback stage on `simulator`** that stays untouched (§6).
- [ ] **Lambda asset built:** `uv run --no-sync python scripts/build_lambda.py`.
- [ ] **Console build is for this stage.** `web/.env.local` is filled from this stage's outputs (`ApiUrl`, `CognitoDomain`, `UserPoolClientId`, `WebUrl` + `/auth/callback`), `VITE_API_MODE` is **not** `mock`, and `cd web ; pnpm build` has run. `deploy --all` uploads whatever is in `web/dist`. A mock build shows the banner *"Demo data… no real calls are placed"*; never film that build as live.
- [ ] **Deployed with the voice provider:** `cd infra ; npx aws-cdk@2 deploy --all -c stage=<stage> -c voice_provider=vobiz`. Optional: `-c retry_wait_minutes=2` (faster recovery; then don't say "30 minutes"). Keep `escalation_hours` at its default of 48 unless you film escalation separately (§5). **Repeat every `-c` flag on every redeploy.**
- [ ] **Off camera, check** that Lambda `jalsakshi-<stage>-task-place-call` → Configuration → Environment variables shows `VOICE_PROVIDER = vobiz`.
- [ ] **Secrets in SSM:** `uv run --no-sync python scripts/put_secrets.py --stage <stage>` (`vobiz_auth_id`, `vobiz_auth_token`, `vobiz_did`, `sarvam_api_key`).
- [ ] **`TEST_NUMBERS` in `.env` has three numbers**, in this order: household 1 (phone A), household 2 (phone B), Nal Jal Mitra (phone C). `.env.example` shows two; the seed refuses fewer than three.
- [ ] **Seed, allowlist, IVR token:** `uv run --no-sync python scripts/seed_demo.py --stage <stage> --allowlist --ivr-token`. Add `--schedules` only after reading the schedule note in §5. The dialler calls only numbers on `/jalsakshi/<stage>/allowed_numbers`. Warm Lambdas cache SSM for up to 5 minutes, so wait 5 minutes after changing it.
- [ ] **Prompts rendered** to this stage: `uv run --no-sync python prompts/render.py --stage <stage>` should print *uploaded 32 clips*. In a browser, `<AudioBaseUrl>/household.q_water.mp3` and `<AudioBaseUrl>/operator.summary_no_supply.n2.mp3` both play (`AudioBaseUrl` is a Data stack output).
- [ ] **Leave `ivr_allowed_cidrs` empty** unless you have verified Vobiz's webhook IPs. A wrong list makes every call silent (webhooks get 404).
- [ ] **Cognito users:** one user in group `PANCHAYAT_SECRETARY` with a neutral username (it appears in the ticket history as `console:<username>`). Optionally a second user in `PHED_AE_SIM` for the department-privacy B-roll. Sign-in on the CloudFront console URL works (it has not been tested yet).
- [ ] **Bedrock works:** after a check-in, **Gram Sabha brief** shows *"Written by the AI agent (Amazon Bedrock, …)"*. If it shows *"Built from the fixed template"*, check the `jalsakshi-<stage>-api` logs off camera before filming.
- [ ] **Full real rehearsal on अमलीडीह today,** through to `CLOSED_VERIFIED`. Note whether *"Maaf kijiye…"* played although a key was pressed, whether the beep and `#` note step works, and how long the phones take to ring.
- [ ] **No open tickets left.** The Villages page shows *No open ticket* for both villages. Finish rehearsal tickets with **Operator reports fixed**, then both households pressing **1**.
- [ ] **Schedules decided** (§5): either take 1 is the 10:30 scheduled run, or both schedules are disabled before 10:30 on Saturday.
- [ ] **Problem card:** a fresh JJM IMIS screenshot with its "as on" date, and card numbers that match it.
- [ ] **Architecture diagram** exported (README mermaid or redrawn).
- [ ] **Shot 1.1** (empty tap, dramatization) filmed.

## B. Filming morning (before the first take)

- [ ] **The IST time is 09:00–20:30.** A take lasts about 5 minutes, and verification calls must also finish before 21:00.
- [ ] **Phones A, B and C:** charged to at least 80%; ringer on and loud; not on silent or Do Not Disturb; call forwarding and waiting off; signal bars present; airplane mode off. Family warned not to call them during takes.
- [ ] **Everyone knows their keys.** DAILY: press **2**, then **#** after the beep, and wait for *"Dhanyavaad…"* before hanging up. Operator: press **1**. Verification: press **1**. Never 1 or 3 on the DAILY question (§2.3).
- [ ] **Filming village is fresh today.** The Villages page shows *Today's calls at 10:30 IST* (no status chip) and *No open ticket*.
- [ ] **No Phone-simulator calls today** on the filming stage's villages.
- [ ] **Dead-letter queues:** the CloudWatch dashboard widget reads 0, or you will not claim it.
- [ ] **Window 1, the JalSakshi console:** signed in; tab 1 is the नयापारा village record; tab 2 is Activity.
- [ ] **Window 2, the AWS console:** region **Mumbai**; six tabs open as in §0, with the DynamoDB query prepared but not run.
- [ ] **Browser hygiene:** zoom 110–125%; other tabs and notifications closed; nothing showing `.env`, SSM, DynamoDB `HH#`/`OP#` items, the Vobiz dashboard or `ivr` logs.
- [ ] **OBS scenes:**
  - 1 Cards (title, IMIS card, limits)
  - 2 Console full
  - 3 Phone camera | AWS window
  - 4 Console | AWS window
  - 5 AWS full
  - 6 Phone simulator (fallback)
  - Recording at 1080p, cursor highlight on.
- [ ] **Audio:** the phone on speaker, next to a separate mic. Levels tested on `household.q_water` (8 kHz phone audio is quiet).
- [ ] **Phone camera** framed on the keypad. The caller ID (the Vobiz DID) on screen is fine.
- [ ] **Fallback stage** (`simulator`) signed in, in a separate browser profile.
- [ ] **One brief opened off camera** to warm the API Lambda.

## C. Every take

- [ ] OBS is recording **before** the first click.
- [ ] **Run check-in now → Yes, start calls**, clicked **once**. Never click it again while calls are in progress, and never use **Start execution** in the Step Functions console.
- [ ] Answer within **40 s** (phones ring for 45 s).
- [ ] **Safety shot:** while phone C rings, click **Close ticket**. Expect *"Only 0 of the 2…"* (`verify-needs-quorum`), then **Dismiss**.
- [ ] **Hero shot:** after household 1's verification *"Dhanyavaad…"* and **before** answering B, click **Close ticket**. Expect *"Only 1 of the 2…"*. Then answer B and press **1**.
- [ ] F5 the ticket page and see the **सत्यापित** stamp; `ticket-flow` reaches `ClosedVerified`.
- [ ] Optional: **Run check-in now** again. Expect the `one-call-per-day` panel; nothing starts.
- [ ] **Gram Sabha brief.** Note whether it says *agent* or *template*, and label the shot to match.
- [ ] Film the dashboard 5 minutes or more after the take.
- [ ] Write down which village and take it was. The next take uses the **other** village, or the next day.

## D. If something goes wrong

| Symptom | Likely cause | Do this |
|---|---|---|
| No ring; Activity at once says *Household … unreachable (attempt 1)* | Dial refused: number not on the allowlist, Vobiz secrets or DID missing | Fix it off camera. The retry comes after `retry_wait_minutes`. Unreachable does not use up the day. |
| Call connects, then silence or an instant hangup | Webhook rejected (`ivr_path_token`, `ivr_allowed_cidrs`) or an IVR crash (it hangs up politely) | Check the `jalsakshi-<stage>-ivr` logs **off camera**. If it is not fixed in 10 minutes, use the fallback (§6). |
| *"Maaf kijiye…"* plays although a key was pressed | Gather timing | Press during the question. After 2 misses the household counts as unreachable. |
| A household pressed 1 or 3 on the DAILY question | Wrong key | The day will not be NO_SUPPLY and no ticket opens. Switch to the other village. |
| Phone C does not ring, or the operator pressed 2 | Dial failed, or "not yet" | On the ticket page, click **नल जल मित्र ने ठीक बताया / Operator reports fixed**. The workflow resumes. Label it *Fix reported from the console*. |
| Close ticket **succeeded** | Both households had already confirmed (correct behaviour) | Use the safety shot ("0 of 2") for 3.2 and adjust the VO. |
| A verification call was missed | The round stays PENDING | The next round comes after `retry_wait_minutes`, calling only the household that has not answered. |
| Brief says *Built from the fixed template* | Bedrock slow (over 24 s) or failing | Reload the page once. Otherwise keep it, labelled *template*. |
| A ticket is stuck open from an earlier attempt | An open ticket blocks new ones | Close it with Operator reports fixed and two verification **1**s, or use the other village. |

## E. After filming

- [ ] Re-enable or delete the schedules as the team decides. Enabled schedules on a `vobiz` stage ring the phones every day.
- [ ] Update `docs/HANDOVER.md`: which stage, villages and takes were used, and where the raw recordings are.

## Open issues that affect filming (owners: see CLAUDE.md)

- `prompts/hi.yaml` `operator.ack_pending` says *"Hum kal phir sampark karenge"* (we will call tomorrow), but no follow-up call exists: `NotifyOperator` just waits, then escalates. Keep it off camera, or reword it (Vamsi).
- `verify.greet` says *"Aapne bataya tha…"* (you told us…) to every household called back. When fewer reporters than the quorum exist, households that never complained are called too. This does not affect the demo, where both reported.
- In the console, the `stale-data` (brief) and `no-household-view-for-dept` (check-ins) denies appear as a plain error box, without the **Blocked by policy** panel or the policy id. To film them as Cedar moments, `BriefPage` / `DayDetail` would need to render `PolicyDenial` for a `PolicyDeniedError` (Varun).
- `.env.example` shows two `TEST_NUMBERS`, but `seed_demo.py` needs three.
