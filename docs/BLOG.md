# JalSakshi: asking the people at the tap whether the water came

*Built for WeMakeDevs x AWS **Environmental Hacks**, Heat & Water track.*
*Demo video: [VIDEO LINK] · Code: [REPO LINK: https://github.com/Galabavamsi/jalsakshi]*

<!-- Before publishing: replace every [PLACEHOLDER], re-verify the figures against docs/RESEARCH.md,
     and update "Where it stands" with what was actually filmed. -->

India's Jal Jeevan Mission has put a tap in most rural homes. Whether water comes out of that tap is a different question. The people who know are the ones who wait at it, often with a shared keypad phone, and nobody calls them to ask. So we built **JalSakshi** (जल साक्षी, "water witness"). It is a short Hindi phone call that asks households whether the water came. When it didn't, JalSakshi opens a repair ticket, and it closes that ticket only when the same households say the water is back.

We are a two-person team, and we built it in a few days on AWS in `ap-south-1` (Mumbai) with Claude Code (Anthropic).

## The problem: a tap is not water

On 30 Sep 2026, Chhattisgarh's Jal Jeevan Mission Director told Collectors to hand finished schemes over to Gram Panchayats at the special Gram Sabhas from 2 October, under the name "Jal Arpan" ([DPR CG](https://dprcg.gov.in/post/1790772080/Raipur-Jal-Arpan-Water-Offering-programs-will-be-held-on-October-2-in-villages-reported-as-Har-Ghar-Jal-Tap-Water-in-Every-Home-completed-schemes-will-be-handed-over-to-Gram-Panchayats-for-operation)). After the handover, the village owns the scheme and all its problems.

- JJM IMIS (as on 07/10/2026): of 19,658 villages in Chhattisgarh, **7,603 are reported as Har Ghar Jal ("tap water in every home"), but only 6,594 are certified** ([report](https://ejalshakti.gov.in/JJM/JJMReports/Physical/JJMRep_HarGharJalVillage.aspx)).
- A CAG audit tabled in July 2026 found villages certified despite incomplete works ([PIB](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2284560&reg=48&lang=2)).
- In Korba, ₹516 crore has been paid, and water reaches about 110 villages under single-village schemes ([ETV Bharat](https://www.etvbharat.com/hi/state/taps-installed-without-water-source-no-water-reached-in-home-jal-jeevan-mission-sorry-state-in-korba-cts26092303858)).
- Nationally, checks found 26% of villages under mega schemes completely non-functional ([NDTV](https://www.ndtv.com/india-news/jal-jeevan-mission-finds-26-villages-without-water-centre-freezes-funds-9711803)).

The official review, *Jal Seva Aankalan*, is a self-assessment by the village water committee ([DoWR](https://www.jalshakti-dowr.gov.in/static/uploads/2026/03/908d7e6b2f8b17a9d61d4733f951e63d.pdf)). It collects no feedback from individual households. Meanwhile groundwater extraction stands at 76.0% in Durg and 92.3% in Bemetara (CGWB 2025, [India-WRIS](https://arc.indiawris.gov.in/server/rest/services/NWIC/GWR2025_CGWB/MapServer/8/query?where=state%3D%27CG%27&outFields=block,district,class,sgw_dev_pe&returnGeometry=false&f=json)), so supply gets harder every summer.

## What JalSakshi does

1. **Asks.** Consenting households get a Hindi call at a time their village chose. It asks whether tap water came today, for how many hours, and whether it was clean. They answer on the keypad, so any phone works.
2. **Decides.** Tested rules turn the answers into a day status: `SUPPLIED`, `PARTIAL`, `NO_SUPPLY`, `DIRTY`, or `UNVERIFIED` if too few households answered.
3. **Acts.** `NO_SUPPLY` or `DIRTY` opens a ticket and calls the pump operator (the *Nal Jal Mitra*) with a Hindi summary.
4. **Verifies.** When the operator presses "fixed", we call the same households back. The ticket becomes `CLOSED_VERIFIED` only if enough of them confirm water. Otherwise it reopens.
5. **Gives evidence.** It writes a Hindi sheet for the Gram Sabha that compares observed supply with the village's claimed status, and every number on it is cited.

We ask several households instead of one person because earlier water-alert pilots found staff self-reports unreliable [CITE: NextDrop study link].

## Code decides, the model only writes

**Decisions are deterministic.** The day status comes from a pure Python function with no I/O, no clock and no LLM. Unreachable households never count as "yes", and every stored status records the `rule_version` that produced it. Ticket transitions are also a pure function: `(ticket, event) -> ticket | Denied`.

**Guard rails are written as policies.** We used [Cedar](https://www.cedarpolicy.com/), the open-source policy language, so that anyone can read the rules:

```cedar
// TRAI calling hours: 09:00 up to (not including) 21:00 IST.
@id("calling-hours")
forbid (principal, action == Action::"PlaceCall", resource)
unless { context.hour_ist >= 9 && context.hour_ist < 21 };
```

Other policies cover consent, no calls after a family says no, a limit on call-backs, quorum before a verified close, privacy for the simulated department, and stale evidence. Every deny comes back as a plain reason in Hindi and English, for example "Only 1 of 2 households confirmed water".

**The model only handles language.** It does two jobs. It turns an optional spoken note into a structured issue, and it writes the Hindi Gram Sabha sheet. We use [Strands Agents](https://strandsagents.com/) on Amazon Bedrock with Claude Haiku 4.5 through the **India** cross-region inference profile (`in.`), so inference stays in Mumbai and Hyderabad. If that fails, we fall back to Nova 2 Lite and then to a template. A validator re-reads every number in the generated text. If any number differs from the tool values, we use the template instead.

Every number a user sees also carries a `SourceTag`: its source, when it was observed and fetched, and its freshness (`live`, `annual`, `simulated`, ...). Simulated data is labelled on screen.

## The architecture

```
EventBridge Scheduler (per village, Asia/Kolkata)
   │
   ▼
Step Functions: CheckInRun ── Map over households ─────────────────────────────┐
   │  Cedar: consent? said no? too many call-backs?                             │
   │  Lambda: place call ──▶ Vobiz (+91 number) ──▶ household's keypad phone    │
   │  .waitForTaskToken (10 min)                         │ webhooks             │
   │        ▲                                            ▼                      │
   │        └── SendTaskSuccess ◀── Lambda: IVR engine ◀── API Gateway          │
   │                                 returns Vobiz XML, Hindi clips via CloudFront
   ▼                                                                            │
Lambda: reconcile (pure rules) ──▶ DynamoDB (single table) ◀────────────────────┘
   │ NO_SUPPLY / DIRTY
   ▼
Step Functions: TicketFlow
   call Nal Jal Mitra ─▶ wait for "fixed" (48 h ⇒ escalate, simulated PHED)
   ─▶ verification calls ─▶ Cedar: quorum? ─▶ CLOSED_VERIFIED | REOPENED

Strands agent on Bedrock (in. India profile) ─▶ number validator ─▶ Hindi Gram Sabha sheet
Operator console: React on S3 + CloudFront, Cognito sign-in, API Gateway ─▶ Lambda
```

The key piece is `waitForTaskToken`. A call takes minutes and depends on someone picking up, so Step Functions places it, stores the task token on the call's DynamoDB item, and waits without running any compute. When Vobiz posts the final webhook, the IVR Lambda calls `SendTaskSuccess`. If nobody answers within 10 minutes, the household is marked `UNREACHABLE` and gets one retry 30 minutes later. TicketFlow waits for the operator the same way, with a 48-hour limit before escalation.

The rest of the stack is Lambda (Python 3.12, Powertools), an API Gateway HTTP API, DynamoDB with point-in-time recovery, S3, Cognito, and CloudWatch alarms and a dashboard. It is all defined in AWS CDK (Python). The 32 Hindi prompts are rendered once with Sarvam Bulbul at 8 kHz and served from CloudFront.

The IVR engine is provider-agnostic. It emits abstract actions (`Play`, `GetDigits`, `Record`, `Hangup`), and adapters turn those into Vobiz XML or into a browser keypad simulator. The simulator runs the same engine and is labelled `simulated`.

## What fought back

**Our coding assistant billed the wrong account.** One Claude Code session had `CLAUDE_CODE_USE_BEDROCK` set in its shell, so it quietly ran through Bedrock on a personal AWS profile and burned credits. Nothing in the terminal looked different. We now check that variable before every session, and the rule is in our `CLAUDE.md`.

**India-WRIS answered from home but not from AWS.** The CGWB groundwater service worked from a home connection and timed out from Lambda. The assessment is annual, so we bundle a dated snapshot as the fallback. The source then reads "bundled snapshot", and `fetched_at` carries the snapshot's date.

**PyPI at about 96 KB/s.** On campus Wi-Fi every `uv sync` was a gamble, and our Lambda asset is about 59 MB of Linux wheels. We pinned everything in `uv.lock` and run commands with `uv run --no-sync`, so nothing starts a download by surprise.

**uv tried to build us as a package.** On Windows, the hatchling build of our own project failed on PE resources. We never needed a wheel, because tests use `pythonpath = src` and a script bundles the Lambda asset. Setting `[tool.uv] package = false` fixed it.

**Vobiz is Plivo-like, not Plivo.** Most of the XML carried over, but the keypad verb is `<Gather>` rather than Plivo's `<GetDigits>`, and it takes `executionTimeout` instead of `timeout`. We follow every `<Gather>` with a `<Redirect>`, so the flow always gets its next turn.

**A zip went through a JSON tool and came out broken.** Binary isn't text. Lambda code now goes up as a file through CDK's asset pipeline.

**Hindi grammar ignores f-strings.** An early operator prompt put the count before a plural noun, so a single complaint became "ek gharon ne" ("one households have"). We rewrote it so the number stands alone: *Shikayat karne wale gharon ki sankhya: {n}* ("number of households that complained: {n}"). That is correct for any count.

**Our own policy blocked us.** We finished deploying around midnight and wanted a real test call. Cedar's `calling-hours` rule refused, and it was right to. (The brief endpoint's first smoke test also got a 403, from `stale-data`, since there were no check-ins yet.) Night tests now run on the simulator.

## Where it stands (as of 9 Oct; [UPDATE BEFORE PUBLISHING])

- **833 Python tests pass**, including Hypothesis property tests. They check that unreachable households never make a quorum, that an extra "no" never improves a status, that answer order doesn't change the result, and that replaying a webhook changes nothing. The console has 61 Vitest tests.
- A development stage runs in `ap-south-1` with four CDK stacks and 14 Lambda functions. It holds two **demo** villages in Durg district, नयापारा and अमलीडीह, seeded and labelled as demo data.
- **A real call works.** On 8 Oct a phone rang from our Vobiz number. Our Lambda served the XML, a keypad press came back, the Lambda replied, and the hangup webhook arrived. That test used a spike Lambda; the full stack still uses the simulator for voice. [UPDATE: full loop on real phones, if filmed.]
- Both Bedrock models answered test requests from `ap-south-1`. [UPDATE: first live Gram Sabha sheet.]

## Honest limits

- The villagers and operator in the video are **our team playing roles**, and the video labels them.
- **PHED escalation is simulated.** There is no public API into IMIS, Meri Panchayat or PHED ticketing, and we never dial government helplines.
- We call only consenting test numbers, between 09:00 and 21:00 IST. Production would need a service-series number and DLT registration through a panchayat or government partner.
- IMIS figures are self-reported by the state, and we show their "as on" date. Groundwater may come from the dated snapshot.
- A quorum of two households is a demo setting, not a sampling design. The calls are Hindi only for now; keypad input keeps them usable for Chhattisgarhi speakers.

## What's next: summer on the same rails

Water stress peaks from February to May. The same pipeline fits two summer problems we have not built yet: **tanker trips** (did the tanker the panchayat paid for actually arrive?) and **heat alerts** (short Hindi warnings on the days that matter). After that come Chhattisgarhi prompts and a real panchayat partner.

## Built with

AWS (Step Functions, EventBridge Scheduler, Lambda, API Gateway, DynamoDB, S3, CloudFront, Cognito, Bedrock, CloudWatch, CDK), Strands Agents, Cedar, Vobiz and Sarvam Bulbul. We built JalSakshi with **Claude Code** (Anthropic) for research, planning and implementation. Inside the product, the model only writes language; deterministic code makes every decision.

Team: Galaba Vamsi ([@Galabavamsi](https://github.com/Galabavamsi)) and Varun ([@VARUN3WARE](https://github.com/VARUN3WARE)).
Video: [VIDEO LINK] · Code: [REPO LINK: https://github.com/Galabavamsi/jalsakshi]
