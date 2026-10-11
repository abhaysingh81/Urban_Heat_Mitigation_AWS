import { useState } from 'react';
import { AWS_SERVICES } from '../content';
import { Seg } from './CityTabs';

type PathKey = 'all' | 'morning' | 'officer';

const NW = 170;
const NH = 56;
const POS: Record<string, [number, number]> = {
  scheduler: [0, 20],
  refresh: [196, 20],
  sns: [392, 20],
  polly: [392, 104],
  s3: [196, 150],
  cloudfront: [0, 250],
  apigw: [196, 250],
  api: [392, 250],
  bedrock: [588, 250],
  dynamo: [392, 340],
};

const EDGES: { from: string; to: string; path: 'morning' | 'officer' }[] = [
  { from: 'scheduler', to: 'refresh', path: 'morning' },
  { from: 'refresh', to: 'sns', path: 'morning' },
  { from: 'refresh', to: 'polly', path: 'morning' },
  { from: 'refresh', to: 's3', path: 'morning' },
  { from: 'cloudfront', to: 'apigw', path: 'officer' },
  { from: 'apigw', to: 'api', path: 'officer' },
  { from: 'api', to: 'bedrock', path: 'officer' },
  { from: 'api', to: 'dynamo', path: 'officer' },
  { from: 'api', to: 's3', path: 'officer' },
];

const SHORT: Record<string, [string, string]> = {
  scheduler: ['EventBridge', 'Scheduler · 06:00 IST'],
  refresh: ['Lambda', 'forecast job'],
  sns: ['SNS', 'heat alert'],
  polly: ['Polly', 'Hindi audio'],
  s3: ['S3', 'data · model · briefs'],
  cloudfront: ['CloudFront', 'web app'],
  apigw: ['API Gateway', 'HTTP API, throttled'],
  api: ['Lambda', 'FastAPI decision engine'],
  bedrock: ['Bedrock', 'Strands agent + guardrail'],
  dynamo: ['DynamoDB', 'plans · audit · reports'],
};

const center = (id: string) => [POS[id][0] + NW / 2, POS[id][1] + NH / 2] as const;

export function AwsFigure() {
  const [path, setPath] = useState<PathKey>('all');
  const on = (p: 'morning' | 'officer') => path === 'all' || path === p;
  const nodeOn = (id: string) =>
    path === 'all' || EDGES.some((e) => e.path === path && (e.from === id || e.to === id));

  return (
    <figure className="figure m-0">
      <style>{`
        @keyframes flow { to { stroke-dashoffset: -24; } }
        .aws-edge-live { stroke-dasharray: 6 6; animation: flow 1.1s linear infinite; }
        @media (prefers-reduced-motion: reduce) { .aws-edge-live { animation: none; } }
      `}</style>
      <div className="mb-5">
        <Seg
          label="Request path"
          value={path}
          onChange={setPath}
          options={[
            { id: 'all', label: 'Whole stack' },
            { id: 'morning', label: '06:00 alert' },
            { id: 'officer', label: 'Officer asks for a plan' },
          ]}
        />
      </div>
      <div className="overflow-x-auto">
        <svg viewBox="-4 0 766 476" className="w-full h-auto min-w-[36rem] ui" role="img" aria-label="HeatRelief architecture on AWS: a scheduled forecast path and an officer request path">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="var(--ink-2)" />
            </marker>
          </defs>
          {EDGES.map((e) => {
            const [x1, y1] = center(e.from);
            const [x2, y2] = center(e.to);
            // stop the line at the target box edge
            const dx = x2 - x1, dy = y2 - y1;
            const t = Math.min(Math.abs((NW / 2 + 3) / (dx || 1e-6)), Math.abs((NH / 2 + 3) / (dy || 1e-6)));
            const live = on(e.path);
            return (
              <line
                key={`${e.from}-${e.to}`}
                x1={x1} y1={y1} x2={x2 - dx * t} y2={y2 - dy * t}
                stroke={live ? (e.path === 'morning' ? 'var(--heat)' : 'var(--cool)') : 'var(--rule)'}
                strokeWidth={live ? 2 : 1.25}
                markerEnd="url(#arrow)"
                className={live && path !== 'all' ? 'aws-edge-live' : undefined}
                style={{ transition: 'stroke 0.25s' }}
              />
            );
          })}
          {Object.keys(POS).map((id) => {
            const [x, y] = POS[id];
            const lit = nodeOn(id);
            return (
              <g key={id} style={{ opacity: lit ? 1 : 0.35, transition: 'opacity 0.25s' }}>
                <rect x={x} y={y} width={NW} height={NH} rx="6" fill="var(--surface)" stroke={lit ? 'var(--ink-2)' : 'var(--rule-strong)'} strokeWidth="1.25" />
                <text x={x + 12} y={y + 23} fontSize="14.5" fontWeight="700" fill="var(--ink)">{SHORT[id][0]}</text>
                <text x={x + 12} y={y + 42} fontSize="12" fill="var(--muted)">{SHORT[id][1]}</text>
              </g>
            );
          })}
          <text x={0} y={240} fontSize="12" fill="var(--muted)">officer &amp; citizen browsers ↓</text>
          <rect x={0} y={420} width={758} height={44} rx="6" fill="var(--sunk)" stroke="var(--rule)" />
          <text x={14} y={447} fontSize="13.5" fill="var(--ink-2)">
            <tspan fontWeight="700" fill="var(--ink)">CloudWatch + Budgets</tspan> · dashboard, alarms on API errors and failed refreshes, monthly spend cap
          </text>
        </svg>
      </div>

      <dl className="mt-8 grid gap-x-10 gap-y-4 sm:grid-cols-2 ui text-[0.92rem]">
        {AWS_SERVICES.filter((s) => s.id !== 'cloudwatch').map((s) => (
          <div key={s.id} style={{ opacity: nodeOn(s.id) ? 1 : 0.45, transition: 'opacity 0.25s' }}>
            <dt className="font-bold" style={{ color: 'var(--ink)' }}>{s.name}</dt>
            <dd className="m-0 mt-0.5 leading-snug" style={{ color: 'var(--ink-2)' }}>{s.job}</dd>
          </div>
        ))}
      </dl>
      <figcaption className="fig-caption">
        <b>One AWS SAM template, two paths.</b> Orange: the scheduled morning job. Teal: an officer asking for a plan and a brief. Source: <code>infra/template.yaml</code>.
      </figcaption>
    </figure>
  );
}
