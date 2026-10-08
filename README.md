# JalSakshi · जल साक्षी

**Water witness. Households confirm whether tap water actually came, and repairs count only when they confirm it's back.**

> Built for **Environmental Hacks** (WeMakeDevs × AWS Builder Center, Bharat Builds Tour), **Heat & Water** track.
> Demo video: _coming soon_ · Live console: _coming soon_

---

## The problem

India's Jal Jeevan Mission has put a tap connection in most rural homes. Whether **water comes out of that tap** is a different question.

- On 30 Sep 2026, Chhattisgarh's Jal Jeevan Mission (JJM) Mission Director told every Collector to hand completed water schemes over to Gram Panchayats ("Jal Arpan") at the special Gram Sabhas from **2 Oct 2026**.
- The official progress report (JJM IMIS, data as on 07/10/2026) shows **7,603 Chhattisgarh villages reported "Har Ghar Jal" (tap water in every home) but only 6,594 certified**. About 1,009 villages are waiting on a Gram Sabha decision.
- A CAG audit tabled in July 2026 found villages certified **despite incomplete works**. In Korba, ₹516 crore has been paid and about 110 villages get water.
- The official review, *Jal Seva Aankalan*, is a once-a-cycle self-assessment by the village water committee. **Nobody asks each household whether water came today.**

The people who know are the women who wait at the tap, usually on a shared keypad phone, in Hindi or Chhattisgarhi.

## What JalSakshi does

1. **Asks.** A short Hindi phone call (works on any keypad phone): *Aaj nal mein paani aaya? Kitne ghante? Saaf tha?* ("Did tap water come today? For how many hours? Was it clean?")
2. **Decides, deterministically.** A tested rule engine (no AI) turns household answers into the village's day status: `SUPPLIED`, `PARTIAL`, `NO_SUPPLY`, `DIRTY`, or `UNVERIFIED` when too few households answered.
3. **Acts.** `NO_SUPPLY` or `DIRTY` opens a repair ticket and calls the village **Nal Jal Mitra** (pump operator) in Hindi.
4. **Verifies.** When the operator says "fixed", JalSakshi **calls the same households back**. The ticket closes as `CLOSED_VERIFIED` only when they confirm water. Otherwise it reopens, and escalates after 48 hours.
5. **Gives evidence.** It produces a Hindi evidence sheet for the **Gram Sabha**: observed reliability against the village's claimed Har Ghar Jal status, with every number sourced.

**Who it serves:** the household that needs water (the beneficiary), and the sarpanch, Panchayat Secretary and pump operator who must act (the operators).
**What changes:** a Gram Sabha certifies, or sends back a defect list, based on evidence from its own households, and a broken pump is fixed and *proven* fixed.

## Architecture

```mermaid
flowchart LR
  S[EventBridge Scheduler<br/>per village, IST] --> C[Step Functions<br/>CheckInRun]
  C -->|Cedar: consent, hours, 1/day| P[Lambda: place call]
  P --> V[(Vobiz +91 DID<br/>Hindi IVR)]
  V -->|webhook| G[API Gateway] --> I[Lambda: IVR engine]
  I -->|SendTaskSuccess| C
  C --> R[Lambda: reconcile<br/>deterministic rules]
  R -->|NO_SUPPLY / DIRTY| T[Step Functions<br/>TicketFlow]
  T --> O[Call Nal Jal Mitra]
  T -->|operator: fixed| VF[Verification calls]
  VF -->|quorum yes, Cedar| CV[CLOSED_VERIFIED]
  R --> D[(DynamoDB)]
  B[Strands agent on Bedrock<br/>in. India profile] --> E[Hindi Gram Sabha sheet]
  D --> W[Operator console<br/>CloudFront + Cognito]
```

| Layer | AWS |
|---|---|
| Orchestration | Step Functions (Map, `waitForTaskToken`, Retry/Catch), EventBridge Scheduler |
| Compute | Lambda (Python 3.12, Powertools), API Gateway HTTP API |
| Data | DynamoDB (single table, PITR), S3 (prompt audio, evidence sheets) |
| AI | Amazon Bedrock (Claude Haiku 4.5 via the **India** cross-region profile, so inference stays in Mumbai and Hyderabad; Nova 2 Lite fallback), **Strands Agents** (open source) |
| Policy | **Cedar** (open source): consent, calling hours, quorum-before-close, department privacy |
| Web | CloudFront + S3, Cognito |
| Ops | CloudWatch dashboard and alarms, AWS CDK (Python), region `ap-south-1` |

Voice: Vobiz Indian DID with our own Lambda serving the call flow. Hindi prompts are voiced by Sarvam Bulbul. Details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Data sources and freshness

| Source | Used for | Freshness |
|---|---|---|
| JJM IMIS Har Ghar Jal report | claimed and certified status | state self-reported, "as on" date shown |
| India-WRIS / CGWB 2025 | groundwater stage of the block | annual assessment |
| Open-Meteo | recent rain (context) | model, not gauge |
| Household check-ins | observed supply | live |

## Honest limits

- **Demo roles are played by our team** (villagers, pump operator), and this is labelled in the video. Calls go only to consenting test numbers.
- **PHED escalation is simulated.** There is no public API into IMIS, Meri Panchayat or PHED ticketing, so we never auto-dial government helplines.
- Production calling needs a service-series number and DLT registration through a panchayat or government partner.
- The MVP is Hindi only; keypad-first design keeps it usable for Chhattisgarhi speakers.

## Run it

Prerequisites: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 20+ + pnpm, AWS CDK, an AWS account with Bedrock access in `ap-south-1`.

```bash
uv sync --all-groups
uv run pytest -q
cp .env.example .env        # add your Sarvam / Vobiz keys locally (never commit)
cd infra && uv run cdk deploy --all -c stage=dev-<you>
```

## Repository layout

```
src/jalsakshi/   core · policy · store · voice · agent · data · handlers
infra/           AWS CDK app
web/             operator console
prompts/         Hindi prompt catalog + renderer
tests/           unit + property tests
docs/            architecture, handover, demo script, research
```

## Team

- **Galaba Vamsi** ([@Galabavamsi](https://github.com/Galabavamsi)): voice, agent, data
- **Varun** ([@VARUN3WARE](https://github.com/VARUN3WARE)): core, infra, console

## AI tools used

Built with **Claude Code** (Anthropic) for research, planning and implementation, as the hackathon rules require us to disclose. In the product itself, Claude Haiku 4.5 on Amazon Bedrock is used only to extract spoken notes and write the Hindi evidence sheet; every decision is made by deterministic code.

## License

MIT
