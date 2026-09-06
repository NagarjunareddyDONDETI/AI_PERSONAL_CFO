import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  GoalPlan,
  GoalType,
  createGoal,
  deleteGoal,
  getGoalTypes,
  getGoals,
} from "../api";
import { inr } from "../lib/format";
import GlassCard from "./GlassCard";

function riskColor(risk: string): string {
  if (risk === "Low") return "#2dd4bf";
  if (risk === "Medium") return "#f59e0b";
  return "#f43f5e";
}

function ProbGauge({ p, risk }: { p: number; risk: string }) {
  const color = riskColor(risk);
  return (
    <div className="flex flex-col items-center">
      <div
        className="flex h-12 w-12 items-center justify-center rounded-full text-xs font-bold"
        style={{ color, border: `2px solid ${color}` }}
      >
        {Math.round(p * 100)}%
      </div>
      <span className="mt-1 text-[10px] text-slate-500">likely</span>
    </div>
  );
}

function GoalCard({ goal, onDelete }: { goal: GoalPlan; onDelete: () => void }) {
  // timeline_months is null when the goal is unreachable within the horizon.
  const months = goal.timeline_months ?? 0;
  const yrs = Math.floor(months / 12);
  const mos = months % 12;
  const timeline = `${yrs ? yrs + "y " : ""}${mos}m`;
  return (
    <motion.div
      initial={{ opacity: 0, y: 16, rotateX: -8 }}
      animate={{ opacity: 1, y: 0, rotateX: 0 }}
      whileHover={{ translateZ: 12, scale: 1.01 }}
      style={{ transformStyle: "preserve-3d" }}
      className="rounded-xl border border-white/10 bg-white/5 p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <span className="text-lg">{goal.icon}</span>
            <span className="truncate">{goal.name || goal.label}</span>
          </p>
          <p className="text-[11px] text-slate-400">
            {goal.label} · target {inr(goal.target_amount)}
          </p>
        </div>
        <ProbGauge p={goal.completion_probability} risk={goal.risk} />
      </div>

      {/* progress */}
      <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-white/10">
        <motion.div
          className="h-full rounded-full bg-gradient-to-r from-teal-accent to-violet-accent"
          initial={{ width: 0 }}
          animate={{ width: `${goal.progress_pct}%` }}
          transition={{ duration: 0.8 }}
        />
      </div>
      <p className="mt-1 text-[11px] text-slate-400">
        {inr(goal.current_saved)} of {inr(goal.target_amount)} ({goal.progress_pct}%)
      </p>

      {/* trajectory sparkline */}
      {goal.trajectory.length > 1 && (
        <div className="mt-2 h-16">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={goal.trajectory}>
              <defs>
                <linearGradient id={`g${goal.id}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2dd4bf" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#2dd4bf" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="month" hide />
              <YAxis hide domain={[0, "dataMax"]} />
              <Tooltip
                contentStyle={{ background: "#0b1220", border: "1px solid #ffffff22", fontSize: 11 }}
                formatter={(v: number) => inr(v)}
                labelFormatter={(m) => `Month ${m}`}
              />
              <Area type="monotone" dataKey="balance" stroke="#2dd4bf" fill={`url(#g${goal.id})`} strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="mt-2 grid grid-cols-3 gap-2 text-center text-[11px]">
        <div className="rounded-md bg-black/20 py-1">
          <p className="text-slate-500">Timeline</p>
          <p className="text-slate-200">{goal.reachable ? timeline : "50y+"}</p>
        </div>
        <div className="rounded-md bg-black/20 py-1">
          <p className="text-slate-500">Need/mo</p>
          <p className="text-slate-200">{inr(goal.required_monthly)}</p>
        </div>
        <div className="rounded-md bg-black/20 py-1">
          <p className="text-slate-500">Risk</p>
          <p style={{ color: riskColor(goal.risk) }}>{goal.risk}</p>
        </div>
      </div>

      {/* Shortfall callout — only when the contribution misses the requirement */}
      {goal.shortfall_monthly > 0 && (
        <p className="mt-2 rounded-md bg-rose-500/10 px-2 py-1 text-[11px] text-rose-200">
          Short by {inr(goal.shortfall_monthly)}/mo. {goal.projected_label}
        </p>
      )}

      <div className="mt-2 flex items-center justify-between">
        <span className="text-[10px] text-slate-500">
          by {goal.target_date} · surplus {inr(goal.monthly_surplus)}/mo
          {goal.annual_return > 0 &&
            ` · ${(goal.annual_return * 100).toFixed(1)}% p.a.`}
        </span>
        <button
          onClick={onDelete}
          className="text-[11px] text-slate-400 hover:text-rose-300 transition-colors"
        >
          Remove
        </button>
      </div>
    </motion.div>
  );
}

export default function GoalPlannerPanel({ delay = 0 }: { delay?: number }) {
  const [types, setTypes] = useState<GoalType[]>([]);
  const [goals, setGoals] = useState<GoalPlan[]>([]);
  const [surplus, setSurplus] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // form
  const [gtype, setGtype] = useState("emergency_fund");
  const [name, setName] = useState("");
  const [target, setTarget] = useState<string>("");
  const [saved, setSaved] = useState<string>("");
  const [months, setMonths] = useState<string>("");
  const [ret, setRet] = useState<string>("");

  async function refresh() {
    try {
      const { goals: g, monthly_surplus } = await getGoals();
      setGoals(g);
      setSurplus(monthly_surplus);
    } catch {
      /* none yet */
    }
  }

  // Adopt the preset's suggested deadline and return when the type changes, so
  // the form starts from a sensible plan instead of blank fields.
  function applyPreset(id: string) {
    setGtype(id);
    const preset = types.find((t) => t.id === id);
    if (!preset) return;
    setMonths(preset.default_months ? String(preset.default_months) : "");
    setRet(
      preset.assumed_return
        ? String(Number((preset.assumed_return * 100).toFixed(2)))
        : ""
    );
  }

  useEffect(() => {
    getGoalTypes()
      .then((t) => {
        setTypes(t.types);
        const first = t.types.find((x) => x.id === "emergency_fund");
        if (first) {
          setMonths(first.default_months ? String(first.default_months) : "");
          setRet(
            first.assumed_return
              ? String(Number((first.assumed_return * 100).toFixed(2)))
              : ""
          );
        }
      })
      .catch(() => {});
    refresh();
  }, []);

  async function add() {
    const targetAmount = Number(target);
    if (busy || !name.trim() || !(targetAmount > 0)) return;
    setBusy(true);
    setError("");
    try {
      await createGoal({
        name: name.trim(),
        goal_type: gtype,
        target_amount: targetAmount,
        current_saved: Number(saved) || 0,
        target_months: Number(months) || null,
        // UI collects a percentage; the API expects a fraction (7 -> 0.07).
        annual_return: Math.min(100, Math.max(0, Number(ret) || 0)) / 100,
      });
      setName("");
      setTarget("");
      setSaved("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create goal.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id?: number) {
    if (!id) return;
    try {
      await deleteGoal(id);
      setGoals((g) => g.filter((x) => x.id !== id));
    } catch {
      /* ignore */
    }
  }

  return (
    <GlassCard
      title="Goal Planner"
      subtitle="Plan any goal — timeline, monthly saving, risk & completion odds"
      delay={delay}
    >
      {/* create form */}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-7">
        <select
          value={gtype}
          onChange={(e) => applyPreset(e.target.value)}
          className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-slate-100 outline-none focus:border-teal-accent/50 lg:col-span-1"
        >
          {types.map((t) => (
            <option key={t.id} value={t.id} className="bg-navy-900">
              {t.icon} {t.label}
            </option>
          ))}
        </select>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Goal name"
          className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-teal-accent/50 lg:col-span-1"
        />
        <input
          type="number"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="Target"
          title="Total money this goal needs — e.g. 300000"
          className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-slate-100 outline-none focus:border-teal-accent/50"
        />
        <input
          type="number"
          value={saved}
          onChange={(e) => setSaved(e.target.value)}
          placeholder="Saved"
          title="How much you've already put toward this goal — the rest is planned for"
          className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-slate-100 outline-none focus:border-teal-accent/50"
        />
        <input
          type="number"
          value={months}
          onChange={(e) => setMonths(e.target.value)}
          placeholder="Months"
          title="Deadline in months to hit the target. Leave 0 to auto-compute from your monthly surplus."
          className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-slate-100 outline-none focus:border-teal-accent/50"
        />
        <input
          type="number"
          step="0.5"
          min="0"
          max="100"
          value={ret}
          onChange={(e) => setRet(e.target.value)}
          placeholder="Return %"
          title="Assumed annual return on the money you set aside, e.g. 7 for 7% a year. Leave blank for no growth."
          className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-slate-100 outline-none focus:border-teal-accent/50"
        />
        <button
          onClick={add}
          disabled={busy || !name.trim() || !(Number(target) > 0)}
          className="rounded-xl bg-gradient-to-r from-teal-accent to-violet-accent px-4 py-2 text-sm font-semibold text-navy-900 disabled:opacity-40"
        >
          {busy ? "Planning…" : "Add goal"}
        </button>
      </div>
      <p className="mt-1 text-[11px] text-slate-500">
        Leave months at 0 to auto-compute the timeline from your monthly surplus
        ({inr(surplus)}/mo). Return % compounds the balance monthly — leave it
        blank to plan on contributions alone.
      </p>

      {error && <p className="mt-2 text-sm text-rose-300">{error}</p>}

      {/* goals grid */}
      <div className="mt-4 grid gap-3 md:grid-cols-2" style={{ perspective: 1000 }}>
        <AnimatePresence>
          {goals.map((g) => (
            <GoalCard key={g.id} goal={g} onDelete={() => remove(g.id)} />
          ))}
        </AnimatePresence>
      </div>

      {goals.length === 0 && (
        <p className="mt-6 text-center text-sm text-slate-400">
          No goals yet. Add one above — your CFO computes the timeline, the monthly
          saving required, and how likely you are to reach it given your surplus.
        </p>
      )}
    </GlassCard>
  );
}
