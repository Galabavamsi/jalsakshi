# Demo script (≤ 3:00, YouTube, public or unlisted)

Judges see only this video, the repo and the writeup. Every claim must be **shown**, and AWS must be **visible on screen**. Label acted roles and simulated parts on screen.

| Time | Shot | On-screen proof |
|---|---|---|
| 0:00–0:20 | An empty tap in a Durg-area village (acted, labelled *"Dramatization: team members"*). Card: "7,603 villages claim Har Ghar Jal · 6,594 certified · handovers began 2 Oct" | JJM IMIS screenshot with its "as on" date |
| 0:20–0:35 | "The official review asks the village committee. Nobody asks the household." The console's village page: *claimed HGJ: yes · observed: unknown* | Console |
| 0:35–1:20 | **The check-in.** The Scheduler fires, and the Step Functions `CheckInRun` graph lights up. A keypad phone rings and the Hindi voice asks; household 1 presses **2** (no water), household 2 presses **2** | Split screen: phone, Step Functions graph, DynamoDB `DAY#` item flipping to `NO_SUPPLY` |
| 1:20–1:40 | A ticket opens and the **Nal Jal Mitra's** phone rings with a Hindi summary | Ticket timeline in the console; `TicketFlow` execution |
| 1:40–2:10 | **Verified repair.** The operator presses 1 ("fixed") and the state becomes `OPERATOR_REPORTED_FIXED`; verification calls go out and both households press 1, giving **`CLOSED_VERIFIED`**. Then the failure case: someone tries to close a ticket without quorum and gets a **Cedar deny** ("Only 1 of 2 households confirmed water") | Cedar decision log; ticket events |
| 2:10–2:30 | The Hindi **Gram Sabha evidence sheet** (Strands agent on Bedrock, India profile), with every number cited | GenAI trace in CloudWatch |
| 2:30–2:50 | Architecture: Scheduler → Step Functions → Lambda → DynamoDB / Bedrock / Cedar, plus the CloudWatch dashboard (calls, statuses, DLQ = 0) | Real consoles |
| 2:50–3:00 | Honest limits (acted roles, PHED simulated, test numbers only) and the summer roadmap: same rails for tanker trips and heat alerts | Text card |

## Recording checklist
- Calls only between **09:00 and 21:00 IST**; pre-schedule the windows with whoever holds the test phones.
- Record two takes of every call. If PSTN fails, use the console's **phone simulator** (same engine) and label it.
- Screen-record the consoles *while* the call happens (OBS, two sources).
- Final cut under 3:00. Upload to YouTube as unlisted, then test the link in a signed-out browser.
