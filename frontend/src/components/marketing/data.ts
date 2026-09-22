/**
 * Content model for the public marketing landing page.
 *
 * Everything here describes capabilities that actually exist in the app — each
 * card maps to a real backend endpoint in `src/api.ts`. Keep it that way: if a
 * feature is removed from the API, remove its card rather than leaving copy
 * that over-promises.
 */

export interface RailCard {
  id: string;
  /** Geometric glyph — matches the marks already used across the dashboard. */
  glyph: string;
  title: string;
  /** One line, always visible on the card face. */
  blurb: string;
  /** Longer line, revealed on hover/focus (the Netflix row-card behaviour). */
  detail: string;
  /** Tailwind gradient classes for the card's artwork panel. */
  tint: string;
}

/** Rail 1 — what happens automatically, the moment a statement is parsed. */
export const ANALYSIS_CARDS: RailCard[] = [
  {
    id: "categorize",
    glyph: "◍",
    title: "Automatic categorisation",
    blurb: "Every transaction sorted, then rolled up by month.",
    detail:
      "Groceries, rent, EMIs, transfers, subscriptions — labelled on import and totalled per category per month, so the first thing you see is where the money actually went.",
    tint: "from-teal-accent/25 via-teal-accent/5 to-transparent",
  },
  {
    id: "health",
    glyph: "◉",
    title: "Financial health score",
    blurb: "One number, with the four inputs that produced it.",
    detail:
      "Savings rate, months of emergency fund, active EMIs and open anomalies combine into a score and a plain-English rating you can track over time.",
    tint: "from-violet-accent/25 via-violet-accent/5 to-transparent",
  },
  {
    id: "anomalies",
    glyph: "◈",
    title: "Anomaly detection",
    blurb: "Category spikes and outsized debits, flagged by severity.",
    detail:
      "Compares each category against its own baseline and surfaces expected-versus-actual for anything unusual, ranked high or medium so you triage the real problems first.",
    tint: "from-rose-400/25 via-rose-400/5 to-transparent",
  },
  {
    id: "forecast",
    glyph: "◐",
    title: "Next-month forecast",
    blurb: "Projected spend, overall and per category.",
    detail:
      "Builds on your own history to estimate what next month costs before it starts, so a bad month is something you see coming instead of something you discover.",
    tint: "from-sky-400/25 via-sky-400/5 to-transparent",
  },
  {
    id: "savings",
    glyph: "◆",
    title: "Savings suggestions",
    blurb: "Specific cuts, each with a rupee figure attached.",
    detail:
      "Per-category actions ranked by estimated monthly saving — not \"spend less on food\", but how much is realistically recoverable and from where.",
    tint: "from-emerald-400/25 via-emerald-400/5 to-transparent",
  },
  {
    id: "explain",
    glyph: "⌁",
    title: "Explainable by default",
    blurb: "Every figure opens into its own reasoning.",
    detail:
      "Each card can show the why, the formula, the exact transactions used, the documents retrieved, a confidence level, and which model answered.",
    tint: "from-amber-400/25 via-amber-400/5 to-transparent",
  },
  {
    id: "memory",
    glyph: "⎔",
    title: "Long-term memory",
    blurb: "It remembers your preferences and goals.",
    detail:
      "Stated constraints and targets persist across sessions, so advice compounds instead of restarting from zero every time you open the app. Clearable whenever you want.",
    tint: "from-teal-accent/25 via-violet-accent/10 to-transparent",
  },
];

/** Rail 2 — the reasoning layer you interact with directly. */
export const INTELLIGENCE_CARDS: RailCard[] = [
  {
    id: "advisor",
    glyph: "●",
    title: "AI advisor chat",
    blurb: "Ask about your own numbers, in your own words.",
    detail:
      "Grounded in your transactions through retrieval, with the conversation kept across sessions. No key configured? It degrades to computed answers instead of breaking.",
    tint: "from-violet-accent/30 via-violet-accent/5 to-transparent",
  },
  {
    id: "debate",
    glyph: "◎",
    title: "Multi-agent debate",
    blurb: "Several advisors argue, then hand you a decision.",
    detail:
      "Each agent takes a stance with its own confidence and key points, then a consensus step resolves the disagreement into prioritised actions you can act on.",
    tint: "from-teal-accent/30 via-teal-accent/5 to-transparent",
  },
  {
    id: "twin",
    glyph: "⬢",
    title: "Digital financial twin",
    blurb: "Your net worth, projected out to retirement.",
    detail:
      "Model salary growth, expense growth, inflation and investment return to see a multi-year trajectory, your retirement corpus, and the monthly income it sustains.",
    tint: "from-sky-400/30 via-violet-accent/8 to-transparent",
  },
  {
    id: "whatif",
    glyph: "◇",
    title: "What-if and EMI simulator",
    blurb: "Pay in full or finance it? See both.",
    detail:
      "Compares total interest, the effect on your health score and whether it is genuinely affordable — with a written explanation of the trade-off, not just a table.",
    tint: "from-amber-400/30 via-amber-400/5 to-transparent",
  },
  {
    id: "goals",
    glyph: "▲",
    title: "Goal planner",
    blurb: "Required monthly contribution, and the odds you hit it.",
    detail:
      "Set a target and date, get the contribution needed, any shortfall, a completion probability, a risk read and a trajectory you can watch fill up.",
    tint: "from-emerald-400/30 via-teal-accent/8 to-transparent",
  },
  {
    id: "voice",
    glyph: "◒",
    title: "Talk to it",
    blurb: "Speech in, speech out.",
    detail:
      "Ask a question out loud and hear the answer back, with a live waveform while it listens. Falls back to typing cleanly when no speech provider is available.",
    tint: "from-rose-400/30 via-violet-accent/8 to-transparent",
  },
  {
    id: "rag",
    glyph: "◓",
    title: "See the retrieval",
    blurb: "Watch which context the answer was built from.",
    detail:
      "Inspect the retrieved chunks and their similarity scores, the pipeline stages, and a 3D view of the embedding space — the usual black box, opened up.",
    tint: "from-violet-accent/30 via-sky-400/8 to-transparent",
  },
];

/**
 * Honest, checkable numbers only — each one is verifiable in the codebase.
 * Resist adding user counts or savings claims we cannot substantiate.
 */
export interface Stat {
  value: number;
  suffix?: string;
  label: string;
  note: string;
}

export const STATS: Stat[] = [
  {
    value: 9,
    label: "statement formats",
    note: "CSV, TSV, TXT, XLSX, XLSM, XLS, ODS, JSON and PDF",
  },
  {
    value: 14,
    label: "analysis capabilities",
    note: "From categorisation to multi-agent debate",
  },
  {
    value: 5,
    label: "workspaces",
    note: "Overview, insights, planning, advisor and memory",
  },
  {
    value: 0,
    label: "third parties",
    note: "Runs on your own server, against your own account",
  },
];

export interface Step {
  index: string;
  title: string;
  body: string;
}

export const STEPS: Step[] = [
  {
    index: "01",
    title: "Bring a statement",
    body: "Drop in a bank export in almost any format — or load a bundled sample if you would rather look around first. All it needs is a date, a description and an amount.",
  },
  {
    index: "02",
    title: "Get the full read in seconds",
    body: "Transactions are categorised, anomalies flagged, next month forecast and your health score computed before you have finished reading this sentence.",
  },
  {
    index: "03",
    title: "Then start asking questions",
    body: "Interrogate the numbers in chat or by voice, pit advisors against each other, simulate an EMI, set a goal, and project your net worth out to retirement.",
  },
];

/** Scrolling strip under the hero. Short, punchy, no sentences. */
export const MARQUEE_ITEMS: string[] = [
  "CSV",
  "Categorisation",
  "XLSX",
  "Anomaly detection",
  "PDF",
  "Forecasting",
  "JSON",
  "Health score",
  "ODS",
  "Goal planning",
  "TSV",
  "EMI simulation",
  "XLS",
  "Net-worth projection",
  "TXT",
  "Voice answers",
  "XLSM",
  "Explainable AI",
];

export interface NavSection {
  id: string;
  label: string;
}

export const NAV_SECTIONS: NavSection[] = [
  { id: "capabilities", label: "Capabilities" },
  { id: "how-it-works", label: "How it works" },
  { id: "intelligence", label: "Intelligence" },
  { id: "trust", label: "Trust" },
];

export const PRIVACY_POINTS = [
  {
    glyph: "⌂",
    title: "Your server, your data",
    body: "The app talks to a backend you run. Statements are analysed there and stored against your account only — there is no shared pool and no broker in the middle.",
  },
  {
    glyph: "✳",
    title: "Passwords properly handled",
    body: "Salted and hashed, never stored in plain text. Sessions expire, and any rejected token drops you straight back to the sign-in screen instead of a half-loaded dashboard.",
  },
  {
    glyph: "⊘",
    title: "Yours to delete",
    body: "Clear the remembered preferences whenever you like, or delete the account outright and take the whole analysis history with it.",
  },
] as const;

export interface FooterColumn {
  heading: string;
  links: { label: string; target: string }[];
}

/** `target` is a section id on this page — the app has no separate routes. */
export const FOOTER_COLUMNS: FooterColumn[] = [
  {
    heading: "Analysis",
    links: [
      { label: "Categorisation", target: "capabilities" },
      { label: "Anomaly detection", target: "capabilities" },
      { label: "Forecasting", target: "capabilities" },
      { label: "Health score", target: "capabilities" },
    ],
  },
  {
    heading: "Intelligence",
    links: [
      { label: "AI advisor", target: "intelligence" },
      { label: "Multi-agent debate", target: "intelligence" },
      { label: "Financial twin", target: "intelligence" },
      { label: "Goal planner", target: "intelligence" },
    ],
  },
  {
    heading: "Getting started",
    links: [
      { label: "How it works", target: "how-it-works" },
      { label: "Supported formats", target: "capabilities" },
      { label: "Explainability", target: "explainability" },
    ],
  },
  {
    heading: "Trust",
    links: [
      { label: "Where data lives", target: "trust" },
      { label: "Account security", target: "trust" },
      { label: "Deleting your data", target: "trust" },
    ],
  },
];
