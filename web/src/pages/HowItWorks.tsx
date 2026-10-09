/** /how — "How JalSakshi works": each step and the AWS service that runs it. No login needed. */

import { Link } from 'react-router-dom';
import { defineMessages } from '../lib/text';
import { Card, Note, PageTitle } from '../ui';

const m = defineMessages({
  title: 'How JalSakshi works',
  intro:
    'Families answer short phone calls on any keypad phone. Everything behind the call runs on AWS in the Mumbai region (ap-south-1).',
  stepsTitle: 'From a phone call to a fixed tap',
  servicesTitle: 'AWS services in JalSakshi',
  outsideTitle: 'Outside AWS',
  outside:
    'Vobiz: the Indian phone number. Sarvam: the Hindi and Chhattisgarhi voice and speech-to-text. Jev and OpenAI Decisions: next-step suggestions, from codes and counts only (no names, numbers or words).',
  rule: 'Statuses, call permissions and closing a complaint are decided by tested rules and Cedar policies, never by AI. AI only reads speech, writes summaries and suggests; a person presses every button.',
  back: '← Back to the console',
});

interface Step {
  what: string;
  aws: string[];
}

const STEPS: Step[] = [
  {
    what: 'The secretary adds families: paste numbers, a photo of the register, or a missed call.',
    aws: ['Amazon Cognito', 'Amazon Bedrock (reads the photo)', 'AWS Lambda'],
  },
  {
    what: 'Each family gets a consent call in its language and presses 1 to agree. The consent is kept on record.',
    aws: ['AWS Lambda (call flow)', 'Amazon API Gateway', 'Amazon DynamoDB'],
  },
  {
    what: 'Every evening each family is asked: did water come today, for how long, was it clean?',
    aws: ['Amazon EventBridge Scheduler', 'AWS Step Functions', 'Cedar policies'],
  },
  {
    what: 'A missed call at any hour is called straight back with the complaint menu, or the family speaks the problem.',
    aws: ['AWS Lambda', 'Amazon S3 (recording)', 'Amazon Bedrock (Claude Haiku)'],
  },
  {
    what: 'Rules turn the answers into each water source’s status and open a numbered complaint.',
    aws: ['AWS Lambda', 'Amazon DynamoDB'],
  },
  {
    what: 'The pump operator gets a call. Press 7 if it cannot be fixed alone: the Sarpanch gets a call with the operator’s words.',
    aws: ['AWS Step Functions (TicketFlow)', 'AWS Lambda'],
  },
  {
    what: 'After "fixed", the same families are called back. The complaint closes only when they confirm water is back.',
    aws: ['AWS Step Functions', 'Cedar policies', 'Amazon DynamoDB'],
  },
  {
    what: 'The console shows an AI overview and a suggested next step on each complaint, plus reports for the Gram Sabha.',
    aws: ['Amazon CloudFront', 'Amazon S3', 'Amazon Bedrock'],
  },
];

const SERVICES: Array<[string, string]> = [
  ['AWS Lambda', '18 small functions: the phone menu, calls, voice notes, the console API'],
  ['AWS Step Functions', 'The evening check-in run and each complaint’s repair-and-confirm flow'],
  ['Amazon EventBridge Scheduler', 'Each village’s daily call time and delayed jobs'],
  ['Amazon API Gateway', 'Phone webhooks, the console API and the residents’ page'],
  ['Amazon DynamoDB', 'Villages, families, consent record, answers, complaints'],
  ['Amazon S3 + CloudFront', 'Recorded prompts, voice-note archive, this console'],
  ['Amazon Bedrock', 'Claude Haiku 5.5 (then 4.5, then Nova 2 Lite): spoken notes, names, register photos, overviews'],
  ['Amazon Cognito', 'Panchayat logins, created by the JalSakshi team'],
  ['AWS Systems Manager Parameter Store', 'Vendor keys, never in code'],
  ['Amazon CloudWatch', 'Dashboard and alarms for failed calls and runs'],
  ['AWS CDK', 'All of the above as code, one stack per stage'],
];

export function HowItWorksPage() {
  return (
    <main className="wrap page">
      <Link className="back" to="/">{m.back}</Link>
      <PageTitle title={m.title} />
      <p>{m.intro}</p>
      <Card title={m.stepsTitle}>
        <ol className="steps how-steps">
          {STEPS.map((s) => (
            <li key={s.what}>
              <span>{s.what}</span>
              <span className="aws">{s.aws.join(' · ')}</span>
            </li>
          ))}
        </ol>
      </Card>
      <Card title={m.servicesTitle}>
        <ul className="rows">
          {SERVICES.map(([name, use]) => (
            <li key={name} className="row">
              <span className="row-main">
                <b>{name}</b>
                <span className="row-sub">{use}</span>
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title={m.outsideTitle}>
        <p>{m.outside}</p>
      </Card>
      <Note>{m.rule}</Note>
    </main>
  );
}
