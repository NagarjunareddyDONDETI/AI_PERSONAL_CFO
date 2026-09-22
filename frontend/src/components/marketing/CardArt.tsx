/**
 * Card artwork for the capability rails.
 *
 * Each capability gets a small vector preview of what that feature actually
 * renders in the dashboard — a donut for categorisation, a gauge for the health
 * score, a spike series for anomalies, and so on. Deliberately not stock
 * photography: these read as product, stay crisp at any pixel density, add no
 * network requests to a self-hosted app, and are a few hundred bytes each.
 *
 * All artwork is decorative. The card's real meaning lives in its heading and
 * copy, so every SVG is aria-hidden and the shapes carry no text alternative.
 */
import { ReactElement, ReactNode } from "react";

// Palette pulled from tailwind.config.js plus a few neighbouring hues, so the
// artwork can differentiate series without leaving the app's identity.
const TEAL = "#2dd4bf";
const VIOLET = "#a78bfa";
const SKY = "#38bdf8";
const AMBER = "#fbbf24";
const ROSE = "#fb7185";
const EMERALD = "#34d399";
const MUTED = "#64748b";

/**
 * Shared canvas. `slice` is important: the artwork panel shrinks on hover to
 * make room for the description, and slicing crops instead of squashing.
 */
function Frame({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 288 128"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
      className="h-full w-full"
    >
      {children}
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/* Rail 1 — automatic analysis                                                */
/* -------------------------------------------------------------------------- */

/** Donut split into spend categories, with a small legend. */
function CategoriseArt() {
  const c = 2 * Math.PI * 34; // circumference, for dasharray segments
  const segments = [
    { color: TEAL, portion: 0.4 },
    { color: VIOLET, portion: 0.25 },
    { color: SKY, portion: 0.2 },
    { color: AMBER, portion: 0.15 },
  ];
  let offset = 0;

  return (
    <Frame>
      <g transform="rotate(-90 84 64)">
        <circle cx="84" cy="64" r="34" fill="none" stroke="#ffffff" strokeOpacity="0.07" strokeWidth="15" />
        {segments.map((s) => {
          const dash = `${c * s.portion - 2} ${c}`;
          const el = (
            <circle
              key={s.color}
              cx="84"
              cy="64"
              r="34"
              fill="none"
              stroke={s.color}
              strokeWidth="15"
              strokeDasharray={dash}
              strokeDashoffset={-offset}
              strokeLinecap="butt"
            />
          );
          offset += c * s.portion;
          return el;
        })}
      </g>
      {segments.map((s, i) => (
        <g key={`legend-${s.color}`}>
          <rect x="150" y={34 + i * 18} width="8" height="8" rx="2" fill={s.color} />
          <rect
            x="166"
            y={36 + i * 18}
            width={72 - i * 14}
            height="4"
            rx="2"
            fill="#ffffff"
            fillOpacity="0.16"
          />
        </g>
      ))}
    </Frame>
  );
}

/** Semicircular score gauge with a needle. */
function HealthArt() {
  const arc = Math.PI * 58; // length of a 58px-radius semicircle
  return (
    <Frame>
      <path
        d="M 86 96 A 58 58 0 0 1 202 96"
        fill="none"
        stroke="#ffffff"
        strokeOpacity="0.09"
        strokeWidth="13"
        strokeLinecap="round"
      />
      <path
        d="M 86 96 A 58 58 0 0 1 202 96"
        fill="none"
        stroke="url(#healthGrad)"
        strokeWidth="13"
        strokeLinecap="round"
        strokeDasharray={`${arc * 0.72} ${arc}`}
      />
      <defs>
        <linearGradient id="healthGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={VIOLET} />
          <stop offset="100%" stopColor={TEAL} />
        </linearGradient>
      </defs>
      {/* Needle at ~72% of the sweep */}
      <line x1="144" y1="96" x2="177" y2="57" stroke="#e5e9f0" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="144" cy="96" r="5" fill="#e5e9f0" />
      <text x="144" y="82" textAnchor="middle" fill="#e5e9f0" fontSize="19" fontWeight="700">
        72
      </text>
    </Frame>
  );
}

/** Category bars sitting on a baseline, with one flagged outlier. */
function AnomalyArt() {
  const bars = [26, 32, 24, 30, 22, 74, 28, 25, 31];
  return (
    <Frame>
      {/* Expected baseline */}
      <line
        x1="24"
        y1="76"
        x2="264"
        y2="76"
        stroke={MUTED}
        strokeWidth="1.5"
        strokeDasharray="5 5"
      />
      {bars.map((h, i) => {
        const spike = h > 60;
        return (
          <rect
            key={i}
            x={28 + i * 26}
            y={104 - h}
            width="13"
            height={h}
            rx="3"
            fill={spike ? ROSE : "#ffffff"}
            fillOpacity={spike ? 0.95 : 0.14}
          />
        );
      })}
      {/* Flag on the outlier */}
      <circle cx="164" cy="24" r="9" fill={ROSE} fillOpacity="0.2" stroke={ROSE} strokeWidth="1.5" />
      <path d="M164 20v5.5" stroke={ROSE} strokeWidth="2" strokeLinecap="round" />
      <circle cx="164" cy="28.5" r="1.1" fill={ROSE} />
    </Frame>
  );
}

/** History as a solid line, next month as a dashed projection inside a cone. */
function ForecastArt() {
  return (
    <Frame>
      <defs>
        <linearGradient id="coneGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={SKY} stopOpacity="0.3" />
          <stop offset="100%" stopColor={SKY} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* Uncertainty cone around the projection */}
      <path d="M168 62 L264 30 L264 96 Z" fill="url(#coneGrad)" />
      {/* Observed history */}
      <polyline
        points="24,88 48,74 72,80 96,60 120,68 144,52 168,62"
        fill="none"
        stroke={SKY}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Projection */}
      <polyline
        points="168,62 216,50 264,44"
        fill="none"
        stroke={SKY}
        strokeWidth="2.5"
        strokeDasharray="6 5"
        strokeLinecap="round"
      />
      <circle cx="168" cy="62" r="4" fill="#0a0e1a" stroke={SKY} strokeWidth="2.5" />
      <circle cx="264" cy="44" r="3.5" fill={SKY} />
      {/* Axis */}
      <line x1="24" y1="104" x2="264" y2="104" stroke="#ffffff" strokeOpacity="0.1" strokeWidth="1.5" />
    </Frame>
  );
}

/** Ranked savings opportunities as descending bars. */
function SavingsArt() {
  const rows = [
    { w: 196, label: "₹4,200" },
    { w: 150, label: "₹2,800" },
    { w: 108, label: "₹1,650" },
    { w: 68, label: "₹900" },
  ];
  return (
    <Frame>
      {rows.map((r, i) => (
        <g key={i}>
          <rect x="24" y={26 + i * 24} width="212" height="12" rx="6" fill="#ffffff" fillOpacity="0.07" />
          <rect x="24" y={26 + i * 24} width={r.w} height="12" rx="6" fill={EMERALD} fillOpacity={0.9 - i * 0.16} />
          <text x={r.w + 32} y={36 + i * 24} fill="#94a3b8" fontSize="9.5" fontWeight="600">
            {r.label}
          </text>
        </g>
      ))}
      <path d="M24 118h240" stroke="#ffffff" strokeOpacity="0.08" strokeWidth="1.5" />
    </Frame>
  );
}

/** A figure branching into the evidence that produced it. */
function ExplainArt() {
  const leaves = [
    { y: 22, label: 58 },
    { y: 52, label: 78 },
    { y: 82, label: 46 },
    { y: 110, label: 66 },
  ];
  return (
    <Frame>
      {leaves.map((l, i) => (
        <path
          key={i}
          d={`M104 64 C 132 64, 140 ${l.y}, 168 ${l.y}`}
          fill="none"
          stroke={AMBER}
          strokeOpacity={0.5 - i * 0.06}
          strokeWidth="1.6"
        />
      ))}
      <circle cx="66" cy="64" r="26" fill={AMBER} fillOpacity="0.14" stroke={AMBER} strokeWidth="1.8" />
      <text x="66" y="70" textAnchor="middle" fill={AMBER} fontSize="15" fontWeight="700">
        why
      </text>
      {leaves.map((l, i) => (
        <g key={`leaf-${i}`}>
          <rect x="168" y={l.y - 8} width="16" height="16" rx="4" fill={AMBER} fillOpacity="0.22" />
          <rect x="190" y={l.y - 3} width={l.label} height="5" rx="2.5" fill="#ffffff" fillOpacity="0.18" />
        </g>
      ))}
    </Frame>
  );
}

/** Stacked layers persisting over a timeline. */
function MemoryArt() {
  return (
    <Frame>
      {[0, 1, 2].map((i) => (
        <rect
          key={i}
          x={44 + i * 14}
          y={22 + i * 16}
          width="150"
          height="34"
          rx="9"
          fill="#ffffff"
          fillOpacity={0.05 + i * 0.04}
          stroke={i === 2 ? TEAL : "#ffffff"}
          strokeOpacity={i === 2 ? 0.5 : 0.08}
          strokeWidth="1.4"
        />
      ))}
      {[0, 1, 2].map((i) => (
        <g key={`row-${i}`}>
          <circle cx={60 + i * 14} cy={39 + i * 16} r="3.5" fill={i === 2 ? TEAL : MUTED} />
          <rect
            x={72 + i * 14}
            y={36 + i * 16}
            width={92 - i * 16}
            height="5"
            rx="2.5"
            fill="#ffffff"
            fillOpacity="0.16"
          />
        </g>
      ))}
      {/* Persistence timeline */}
      <line x1="24" y1="112" x2="264" y2="112" stroke="#ffffff" strokeOpacity="0.1" strokeWidth="1.5" />
      {[0, 1, 2, 3, 4].map((i) => (
        <circle key={`tick-${i}`} cx={40 + i * 52} cy="112" r="3" fill={i === 4 ? TEAL : MUTED} />
      ))}
    </Frame>
  );
}

/* -------------------------------------------------------------------------- */
/* Rail 2 — the reasoning layer                                               */
/* -------------------------------------------------------------------------- */

/** A short conversation, mid-reply. */
function AdvisorArt() {
  return (
    <Frame>
      {/* Incoming question */}
      <rect x="24" y="20" width="150" height="34" rx="12" fill="#ffffff" fillOpacity="0.08" />
      <rect x="38" y="30" width="98" height="5" rx="2.5" fill="#ffffff" fillOpacity="0.22" />
      <rect x="38" y="41" width="62" height="5" rx="2.5" fill="#ffffff" fillOpacity="0.14" />
      {/* Answer */}
      <rect x="86" y="62" width="178" height="40" rx="12" fill={VIOLET} fillOpacity="0.18" stroke={VIOLET} strokeOpacity="0.4" strokeWidth="1.2" />
      <rect x="100" y="73" width="132" height="5" rx="2.5" fill={VIOLET} fillOpacity="0.65" />
      <rect x="100" y="85" width="96" height="5" rx="2.5" fill={VIOLET} fillOpacity="0.4" />
      {/* Typing indicator */}
      <g>
        <circle cx="36" cy="112" r="3.5" fill={MUTED} />
        <circle cx="48" cy="112" r="3.5" fill={MUTED} fillOpacity="0.6" />
        <circle cx="60" cy="112" r="3.5" fill={MUTED} fillOpacity="0.3" />
      </g>
    </Frame>
  );
}

/** Three advisors converging on one consensus node. */
function DebateArt() {
  const agents = [
    { x: 40, y: 30, color: TEAL },
    { x: 34, y: 96, color: VIOLET },
    { x: 92, y: 20, color: SKY },
  ];
  return (
    <Frame>
      {agents.map((a, i) => (
        <line
          key={i}
          x1={a.x}
          y1={a.y}
          x2="196"
          y2="64"
          stroke={a.color}
          strokeOpacity="0.35"
          strokeWidth="1.5"
          strokeDasharray="4 4"
        />
      ))}
      {agents.map((a, i) => (
        <g key={`agent-${i}`}>
          <circle cx={a.x} cy={a.y} r="13" fill={a.color} fillOpacity="0.18" stroke={a.color} strokeWidth="1.6" />
          <circle cx={a.x} cy={a.y} r="4" fill={a.color} />
        </g>
      ))}
      {/* Consensus */}
      <circle cx="196" cy="64" r="30" fill={TEAL} fillOpacity="0.12" stroke={TEAL} strokeWidth="1.8" />
      <path d="M184 64l8 8 16-17" fill="none" stroke={TEAL} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      {/* Confidence bars */}
      {[46, 30, 38].map((w, i) => (
        <rect key={`conf-${i}`} x="238" y={44 + i * 14} width={w} height="5" rx="2.5" fill={agents[i].color} fillOpacity="0.5" />
      ))}
    </Frame>
  );
}

/** Net worth compounding, with scenario branches. */
function TwinArt() {
  return (
    <Frame>
      <defs>
        <linearGradient id="twinGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={SKY} stopOpacity="0.42" />
          <stop offset="100%" stopColor={SKY} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d="M24 104 C 80 100, 120 82, 156 62 C 196 40, 230 30, 264 22 L264 104 Z" fill="url(#twinGrad)" />
      <path
        d="M24 104 C 80 100, 120 82, 156 62 C 196 40, 230 30, 264 22"
        fill="none"
        stroke={SKY}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      {/* Optimistic / cautious branches diverging from the midpoint */}
      <path d="M156 62 C 196 48, 226 44, 264 42" fill="none" stroke={VIOLET} strokeWidth="2" strokeDasharray="6 5" strokeOpacity="0.75" />
      <path d="M156 62 C 196 58, 226 60, 264 62" fill="none" stroke={MUTED} strokeWidth="2" strokeDasharray="6 5" strokeOpacity="0.7" />
      <circle cx="156" cy="62" r="4.5" fill="#0a0e1a" stroke={SKY} strokeWidth="2.5" />
      <line x1="24" y1="112" x2="264" y2="112" stroke="#ffffff" strokeOpacity="0.1" strokeWidth="1.5" />
    </Frame>
  );
}

/** Pay in full versus finance, side by side. */
function WhatIfArt() {
  return (
    <Frame>
      {/* Option A — pay in full */}
      <rect x="34" y="46" width="72" height="58" rx="8" fill={TEAL} fillOpacity="0.2" stroke={TEAL} strokeOpacity="0.5" strokeWidth="1.4" />
      <rect x="48" y="30" width="44" height="5" rx="2.5" fill="#ffffff" fillOpacity="0.24" />
      {/* Option B — EMI, taller because of interest */}
      <rect x="182" y="26" width="72" height="78" rx="8" fill={AMBER} fillOpacity="0.2" stroke={AMBER} strokeOpacity="0.5" strokeWidth="1.4" />
      <rect x="196" y="30" width="44" height="5" rx="2.5" fill="#ffffff" fillOpacity="0.24" />
      {/* Interest delta highlighted on top of option B */}
      <rect x="182" y="26" width="72" height="22" rx="8" fill={AMBER} fillOpacity="0.4" />
      {/* Divider + comparison marker */}
      <line x1="144" y1="20" x2="144" y2="110" stroke="#ffffff" strokeOpacity="0.12" strokeWidth="1.5" strokeDasharray="4 5" />
      <circle cx="144" cy="64" r="13" fill="#0a0e1a" stroke="#ffffff" strokeOpacity="0.25" strokeWidth="1.4" />
      <text x="144" y="69" textAnchor="middle" fill="#94a3b8" fontSize="11" fontWeight="700">
        vs
      </text>
      <line x1="24" y1="112" x2="264" y2="112" stroke="#ffffff" strokeOpacity="0.1" strokeWidth="1.5" />
    </Frame>
  );
}

/** Goal progress ring with a target marker. */
function GoalArt() {
  const c = 2 * Math.PI * 40;
  return (
    <Frame>
      <g transform="rotate(-90 144 64)">
        <circle cx="144" cy="64" r="40" fill="none" stroke="#ffffff" strokeOpacity="0.08" strokeWidth="12" />
        <circle
          cx="144"
          cy="64"
          r="40"
          fill="none"
          stroke="url(#goalGrad)"
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={`${c * 0.68} ${c}`}
        />
      </g>
      <defs>
        <linearGradient id="goalGrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={EMERALD} />
          <stop offset="100%" stopColor={TEAL} />
        </linearGradient>
      </defs>
      <text x="144" y="70" textAnchor="middle" fill="#e5e9f0" fontSize="20" fontWeight="700">
        68%
      </text>
      {/* Target flag */}
      <circle cx="144" cy="24" r="4.5" fill={EMERALD} />
      <rect x="60" y="58" width="34" height="5" rx="2.5" fill="#ffffff" fillOpacity="0.14" />
      <rect x="60" y="70" width="22" height="5" rx="2.5" fill="#ffffff" fillOpacity="0.1" />
      <rect x="194" y="58" width="34" height="5" rx="2.5" fill="#ffffff" fillOpacity="0.14" />
      <rect x="206" y="70" width="22" height="5" rx="2.5" fill="#ffffff" fillOpacity="0.1" />
    </Frame>
  );
}

/** Mic with a live waveform. */
function VoiceArt() {
  // Symmetric about the centre axis, so the waveform reads as amplitude rather
  // than as an arbitrary bar chart.
  const heights = [16, 28, 44, 62, 40, 54, 24, 44, 18, 32, 14, 22];
  const MIC_X = 60; // vertical axis every mic part is centred on
  return (
    <Frame>
      <defs>
        <radialGradient id="voiceOrb" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={ROSE} stopOpacity="0.34" />
          <stop offset="70%" stopColor={ROSE} stopOpacity="0.12" />
          <stop offset="100%" stopColor={ROSE} stopOpacity="0" />
        </radialGradient>
        <linearGradient id="voiceWave" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={VIOLET} />
          <stop offset="100%" stopColor={ROSE} />
        </linearGradient>
      </defs>

      {/* Listening rings, widening and fading outward from the orb */}
      <circle cx={MIC_X} cy="64" r="34" fill="none" stroke={ROSE} strokeOpacity="0.1" strokeWidth="1.2" />
      <circle cx={MIC_X} cy="64" r="28" fill="none" stroke={ROSE} strokeOpacity="0.2" strokeWidth="1.2" />
      <circle cx={MIC_X} cy="64" r="22" fill="url(#voiceOrb)" stroke={ROSE} strokeOpacity="0.55" strokeWidth="1.6" />

      {/* Microphone: capsule, cradle, stand, base — all centred on MIC_X and
          sized so the cradle arms flank the capsule instead of swallowing it. */}
      <rect x={MIC_X - 6} y="48" width="12" height="19" rx="6" fill={ROSE} fillOpacity="0.9" />
      {[54, 58, 62].map((y) => (
        <line
          key={y}
          x1={MIC_X - 3.5}
          y1={y}
          x2={MIC_X + 3.5}
          y2={y}
          stroke="#0a0e1a"
          strokeOpacity="0.45"
          strokeWidth="1.1"
          strokeLinecap="round"
        />
      ))}
      <path
        d={`M${MIC_X - 10} 62 A 10 10 0 0 0 ${MIC_X + 10} 62`}
        fill="none"
        stroke={ROSE}
        strokeWidth="2"
        strokeLinecap="round"
      />
      <line x1={MIC_X} y1="72" x2={MIC_X} y2="80" stroke={ROSE} strokeWidth="2" strokeLinecap="round" />
      <line x1={MIC_X - 8} y1="80" x2={MIC_X + 8} y2="80" stroke={ROSE} strokeWidth="2" strokeLinecap="round" />

      {/* Waveform */}
      <line x1="98" y1="64" x2="262" y2="64" stroke="#ffffff" strokeOpacity="0.07" strokeWidth="1" />
      {heights.map((h, i) => (
        <rect
          key={i}
          x={102 + i * 13.5}
          y={64 - h / 2}
          width="6"
          height={h}
          rx="3"
          fill="url(#voiceWave)"
          fillOpacity={0.35 + (h / 62) * 0.55}
        />
      ))}
    </Frame>
  );
}

/** Query node pulling in ranked document chunks. */
function RagArt() {
  const docs = [
    { y: 22, score: "0.94", opacity: 0.85 },
    { y: 56, score: "0.81", opacity: 0.6 },
    { y: 90, score: "0.67", opacity: 0.38 },
  ];
  return (
    <Frame>
      {docs.map((d, i) => (
        <line
          key={i}
          x1="76"
          y1="64"
          x2="168"
          y2={d.y + 13}
          stroke={VIOLET}
          strokeOpacity={d.opacity * 0.55}
          strokeWidth="1.6"
        />
      ))}
      <circle cx="52" cy="64" r="24" fill={VIOLET} fillOpacity="0.16" stroke={VIOLET} strokeWidth="1.7" />
      <circle cx="52" cy="64" r="9" fill={VIOLET} fillOpacity="0.7" />
      {docs.map((d, i) => (
        <g key={`doc-${i}`}>
          <rect
            x="168"
            y={d.y}
            width="26"
            height="26"
            rx="5"
            fill={SKY}
            fillOpacity={d.opacity * 0.3}
            stroke={SKY}
            strokeOpacity={d.opacity}
            strokeWidth="1.3"
          />
          <rect x="173" y={d.y + 7} width="16" height="3" rx="1.5" fill={SKY} fillOpacity={d.opacity} />
          <rect x="173" y={d.y + 14} width="11" height="3" rx="1.5" fill={SKY} fillOpacity={d.opacity * 0.7} />
          <text x="204" y={d.y + 17} fill="#94a3b8" fontSize="10" fontWeight="600">
            {d.score}
          </text>
        </g>
      ))}
    </Frame>
  );
}

/** Fallback so a new card without bespoke artwork still renders something. */
function GenericArt() {
  return (
    <Frame>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <rect
          key={i}
          x={28 + i * 40}
          y={104 - (24 + ((i * 17) % 52))}
          width="24"
          height={24 + ((i * 17) % 52)}
          rx="5"
          fill={TEAL}
          fillOpacity={0.18 + i * 0.06}
        />
      ))}
    </Frame>
  );
}

/** Keyed by the card `id` values in `data.ts`. */
const ART: Record<string, () => ReactElement> = {
  categorize: CategoriseArt,
  health: HealthArt,
  anomalies: AnomalyArt,
  forecast: ForecastArt,
  savings: SavingsArt,
  explain: ExplainArt,
  memory: MemoryArt,
  advisor: AdvisorArt,
  debate: DebateArt,
  twin: TwinArt,
  whatif: WhatIfArt,
  goals: GoalArt,
  voice: VoiceArt,
  rag: RagArt,
};

export default function CardArt({ id }: { id: string }) {
  const Art = ART[id] ?? GenericArt;
  return <Art />;
}
