import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Capabilities, DashboardData } from "../api";
import { inr, monthLabel } from "../lib/format";
import { useHashRoute } from "../lib/useHashRoute";
import AnimatedNumber from "./AnimatedNumber";
import AnomaliesPanel from "./AnomaliesPanel";
import CategoryChart from "./CategoryChart";
import ChatPanel from "./ChatPanel";
import DebatePanel from "./DebatePanel";
import ErrorBoundary from "./ErrorBoundary";
import ExplainabilityPanel from "./ExplainabilityPanel";
import ForecastChart from "./ForecastChart";
import GoalPlannerPanel from "./GoalPlannerPanel";
import HealthScorePanel from "./HealthScorePanel";
import MemoryPanel from "./MemoryPanel";
import PageNav, { PAGE_IDS, PageId } from "./PageNav";
import PageShell, { Row, Wide } from "./PageShell";
import RetrievalPanel from "./RetrievalPanel";
import SavingsPanel from "./SavingsPanel";
import TwinPanel from "./TwinPanel";
import VoiceAssistant from "./VoiceAssistant";
import WhatIfPanel from "./WhatIfPanel";

function StatCard({
  label,
  value,
  accent,
  delay,
}: {
  label: string;
  value: number;
  accent: string;
  delay: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="glass rounded-2xl p-4"
    >
      <p className="text-[11px] uppercase tracking-wider text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-extrabold" style={{ color: accent }}>
        <AnimatedNumber value={value} format={(n) => inr(n)} />
      </p>
    </motion.div>
  );
}

export default function Dashboard({
  data,
  capabilities,
}: {
  data: DashboardData;
  capabilities: Capabilities | null;
}) {
  const hs = data.health_score;
  const ref = hs.reference_month;
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [page, navigate] = useHashRoute<PageId>(PAGE_IDS, "overview");

  return (
    <div className="ambient-bg min-h-screen">
      <PageNav active={page} onNavigate={navigate} />

      {/* `mode="wait"` lets the outgoing page finish before the next enters, so
          switching views is one clean transition rather than two overlapping. */}
      <AnimatePresence mode="wait">
        {page === "overview" && (
          <PageShell
            key="overview"
            eyebrow="Overview"
            title="Financial health"
            description={`Where you stand right now, based on ${
              data.monthly_summary.months.length
            } month(s) of statements${ref ? ` · scored on ${monthLabel(ref)}` : ""}.`}
          >
            <Row>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <StatCard label="Monthly income" value={hs.income} accent="#4ade80" delay={0.05} />
                <StatCard label="Monthly expenses" value={hs.expenses} accent="#fb923c" delay={0.1} />
                <StatCard
                  label="Monthly surplus"
                  value={hs.income - hs.expenses}
                  accent="#2dd4bf"
                  delay={0.15}
                />
                <StatCard
                  label="Next month forecast"
                  value={data.forecast.total_expense_forecast}
                  accent="#a78bfa"
                  delay={0.2}
                />
              </div>
            </Row>

            <HealthScorePanel hs={hs} delay={0.25} />
            <Wide>
              <CategoryChart
                summary={data.monthly_summary}
                transactions={data.transactions}
                delay={0.3}
              />
            </Wide>
            <Row>
              <ForecastChart forecast={data.forecast} delay={0.35} />
            </Row>
          </PageShell>
        )}

        {page === "insights" && (
          <PageShell
            key="insights"
            eyebrow="Insights"
            title="What stands out"
            description="Unusual spending, where you could save, and a full audit trail for every figure."
          >
            <Wide>
              <AnomaliesPanel anomalies={data.anomalies} delay={0.05} />
            </Wide>
            <SavingsPanel suggestions={data.savings_suggestions} delay={0.1} />
            <Row>
              <ExplainabilityPanel delay={0.15} />
            </Row>
          </PageShell>
        )}

        {page === "planning" && (
          <PageShell
            key="planning"
            eyebrow="Planning"
            title="Model your decisions"
            description="Test a purchase, plan a goal, and project your finances decades ahead."
          >
            <Row>
              <WhatIfPanel data={data} delay={0.05} />
            </Row>
            <Row>
              <GoalPlannerPanel delay={0.1} />
            </Row>
            <Row>
              <TwinPanel delay={0.15} />
            </Row>
          </PageShell>
        )}

        {page === "advisor" && (
          <PageShell
            key="advisor"
            eyebrow="Advisor"
            title="Ask your CFO"
            description="Chat grounded in your own statement, or convene the specialist panel for a debated recommendation."
          >
            <Row>
              <ChatPanel capabilities={capabilities} delay={0.05} />
            </Row>
            <Row>
              <DebatePanel delay={0.1} />
            </Row>
          </PageShell>
        )}

        {page === "memory" && (
          <PageShell
            key="memory"
            eyebrow="Memory"
            title="What your CFO knows"
            description="The durable facts it remembers about you, and exactly how it retrieves them to answer a question."
          >
            <Row>
              <MemoryPanel delay={0.05} />
            </Row>
            <Row>
              <RetrievalPanel delay={0.1} />
            </Row>
          </PageShell>
        )}
      </AnimatePresence>

      <p className="mx-auto max-w-7xl px-4 pb-10 text-center text-xs text-slate-500 md:px-6">
        All figures are computed deterministically from your statement. The AI
        assistant explains them — it never invents numbers.
      </p>

      {/* Floating voice-assistant launcher — global, so it is reachable from
          every page rather than only from the bottom of one long scroll. */}
      <motion.button
        onClick={() => setVoiceOpen(true)}
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.6 }}
        whileHover={{ scale: 1.08 }}
        whileTap={{ scale: 0.95 }}
        title="Talk to your CFO"
        aria-label="Talk to your CFO"
        className="fixed bottom-6 right-6 z-40 flex h-16 w-16 items-center justify-center rounded-full border border-cyan-400/40 bg-navy-900/70 text-2xl backdrop-blur"
        style={{ boxShadow: "0 0 20px rgba(34,211,238,0.55)" }}
      >
        <span
          className="absolute inset-0 rounded-full"
          style={{
            background:
              "radial-gradient(circle at 50% 50%, rgba(56,189,248,0.25), transparent 70%)",
          }}
        />
        <span className="relative">🎙️</span>
      </motion.button>

      <AnimatePresence>
        {voiceOpen && (
          <ErrorBoundary
            fallback={
              <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-navy-900/95 px-6 text-center">
                <p className="text-lg text-slate-100">
                  The voice assistant couldn't start on this device.
                </p>
                <p className="mt-2 max-w-md text-sm text-slate-400">
                  Your browser may not support WebGL/microphone access. You can
                  still ask questions from the Advisor page.
                </p>
                <button
                  onClick={() => setVoiceOpen(false)}
                  className="mt-5 rounded-xl bg-teal-accent px-5 py-2.5 text-sm font-semibold text-navy-900"
                >
                  Close
                </button>
              </div>
            }
          >
            <VoiceAssistant
              capabilities={capabilities}
              onClose={() => setVoiceOpen(false)}
            />
          </ErrorBoundary>
        )}
      </AnimatePresence>
    </div>
  );
}
