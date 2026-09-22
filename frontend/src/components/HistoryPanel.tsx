import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArchivedStatement,
  DashboardData,
  StatementSummary,
  deleteStatement,
  getStatement,
  listStatements,
  restoreStatement,
} from "../api";
import { categoryColor, inr } from "../lib/format";
import GlassCard from "./GlassCard";

/**
 * Statement history.
 *
 * The dashboard's other panels all read the *active* snapshot, which every new
 * upload replaces. This panel reads the append-only archive instead, so a past
 * statement can be opened, searched transaction by transaction, promoted back to
 * active, or deleted.
 *
 * Rendering is capped and grows on demand: a year of statements can run to
 * thousands of rows, and laying them all out at once stalls the page.
 */

const PAGE_SIZE = 100;

type SortKey = "date" | "amount";
type SortDir = "asc" | "desc";

/** "2026-08-12" -> "12 Aug 2026", parsed as a local date (no UTC shift). */
function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** Full ISO timestamp -> "12 Aug 2026, 14:09". */
function stamp(iso: string): string {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function scoreTone(score: number | null): string {
  if (score === null) return "#94a3b8";
  if (score >= 70) return "#4ade80";
  if (score >= 40) return "#fbbf24";
  return "#fb7185";
}

interface Props {
  /** Lets a restored statement refresh the rest of the dashboard. */
  onRestored?: (data: DashboardData) => void;
  delay?: number;
}

export default function HistoryPanel({ onRestored, delay = 0 }: Props) {
  const [statements, setStatements] = useState<StatementSummary[]>([]);
  const [selected, setSelected] = useState<ArchivedStatement | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  // Which statement this session promoted to active. Local on purpose: the
  // backend stores the active snapshot's contents, not which archive row it came
  // from, so claiming a persistent "active" flag would be a lie after a reload.
  const [activatedId, setActivatedId] = useState<number | null>(null);
  const [error, setError] = useState("");

  // Ledger controls
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [visible, setVisible] = useState(PAGE_SIZE);

  async function loadList(preferId?: number) {
    setLoadingList(true);
    try {
      const { statements: rows } = await listStatements();
      setStatements(rows);
      // Default to the newest statement so the ledger is never empty on arrival.
      const next = preferId ?? rows[0]?.id ?? null;
      setSelectedId(next);
      if (next === null) setSelected(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load history");
    } finally {
      setLoadingList(false);
    }
  }

  useEffect(() => {
    loadList();
  }, []);

  // Fetch the payload for whichever statement is selected.
  useEffect(() => {
    if (selectedId === null) return;
    let cancelled = false;
    setLoadingDetail(true);
    getStatement(selectedId)
      .then((rec) => {
        if (cancelled) return;
        setSelected(rec);
        // Reset the ledger view so filters from the previous statement do not
        // silently hide everything in the new one.
        setQuery("");
        setCategory("all");
        setVisible(PAGE_SIZE);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load statement");
        }
      })
      .finally(() => !cancelled && setLoadingDetail(false));
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  async function activate(id: number) {
    setBusyId(id);
    setError("");
    try {
      const data = await restoreStatement(id);
      setActivatedId(id);
      onRestored?.(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not restore statement");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(id: number) {
    setBusyId(id);
    setError("");
    try {
      await deleteStatement(id);
      setConfirmId(null);
      if (activatedId === id) setActivatedId(null);
      // Keep the current selection unless it is the row that just went away.
      await loadList(selectedId === id ? undefined : selectedId ?? undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete statement");
    } finally {
      setBusyId(null);
    }
  }

  const txns = selected?.payload.transactions ?? [];

  const categories = useMemo(() => {
    return Array.from(new Set(txns.map((t) => t.category).filter(Boolean))).sort();
  }, [txns]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = txns.filter((t) => {
      if (category !== "all" && t.category !== category) return false;
      if (!q) return true;
      return (
        t.description.toLowerCase().includes(q) ||
        (t.category || "").toLowerCase().includes(q)
      );
    });
    const dir = sortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      if (sortKey === "amount") return (a.amount - b.amount) * dir;
      return a.date.localeCompare(b.date) * dir;
    });
  }, [txns, query, category, sortKey, sortDir]);

  // Totals describe the filtered set, so they stay meaningful while searching.
  const totals = useMemo(() => {
    let inc = 0;
    let exp = 0;
    for (const t of filtered) {
      if (t.amount > 0) inc += t.amount;
      else exp -= t.amount;
    }
    return { inc, exp };
  }, [filtered]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "date" ? "desc" : "asc");
    }
    setVisible(PAGE_SIZE);
  }

  const sortIndicator = (key: SortKey) =>
    key === sortKey ? (sortDir === "asc" ? "↑" : "↓") : "";

  return (
    <GlassCard
      title="Statement History"
      subtitle={
        loadingList
          ? "Loading…"
          : `${statements.length} statement${
              statements.length === 1 ? "" : "s"
            } archived · newest first`
      }
      delay={delay}
    >
      {error && <p className="mb-3 text-sm text-rose-300">{error}</p>}

      {!loadingList && statements.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-400">
          No statements archived yet. Upload a statement and it will be kept here
          so you can come back to it after the next one.
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,19rem)_minmax(0,1fr)]">
          {/* ---------------- Statement list ---------------- */}
          <ul
            role="list"
            aria-label="Archived statements"
            className="max-h-[32rem] space-y-2 overflow-y-auto pr-1"
          >
            {statements.map((s) => {
              const isSelected = s.id === selectedId;
              const confirming = confirmId === s.id;
              return (
                <li key={s.id}>
                  <div
                    className={`rounded-xl border p-3 transition-colors ${
                      isSelected
                        ? "border-teal-accent/50 bg-teal-accent/5"
                        : "border-white/10 bg-white/5 hover:border-white/20"
                    }`}
                  >
                    <button
                      onClick={() => setSelectedId(s.id)}
                      aria-current={isSelected ? "true" : undefined}
                      className="w-full text-left"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-[13px] font-semibold text-slate-100">
                            {s.filename || "Unnamed statement"}
                          </p>
                          <p className="mt-0.5 text-[11px] text-slate-400">
                            {stamp(s.created_at)}
                          </p>
                        </div>
                        {s.score !== null && (
                          <span
                            title="Financial health score"
                            className="shrink-0 rounded-md px-1.5 py-0.5 text-[11px] font-bold"
                            style={{
                              color: scoreTone(s.score),
                              background: `${scoreTone(s.score)}1f`,
                            }}
                          >
                            {s.score}
                          </span>
                        )}
                      </div>

                      <p className="mt-2 text-[11px] text-slate-400">
                        {s.txn_count} transactions
                        {s.period_start && s.period_end && (
                          <>
                            {" · "}
                            {shortDate(s.period_start)} – {shortDate(s.period_end)}
                          </>
                        )}
                      </p>
                      <p className="mt-1 flex gap-3 text-[11px]">
                        <span className="text-emerald-300">
                          +{inr(s.total_income, { compact: true })}
                        </span>
                        <span className="text-orange-300">
                          −{inr(s.total_expenses, { compact: true })}
                        </span>
                      </p>
                    </button>

                    <div className="mt-2.5 flex items-center gap-2 border-t border-white/5 pt-2">
                      {activatedId === s.id ? (
                        <span className="rounded-md bg-teal-accent/15 px-2 py-1 text-[11px] font-semibold text-teal-accent">
                          Active now
                        </span>
                      ) : (
                        <button
                          onClick={() => activate(s.id)}
                          disabled={busyId === s.id}
                          className="rounded-md bg-white/10 px-2 py-1 text-[11px] font-semibold text-slate-200 transition-colors hover:bg-white/20 disabled:opacity-40"
                          title="Load this statement into the whole dashboard"
                        >
                          {busyId === s.id ? "Loading…" : "Make active"}
                        </button>
                      )}

                      {confirming ? (
                        <>
                          <button
                            onClick={() => remove(s.id)}
                            disabled={busyId === s.id}
                            className="rounded-md bg-rose-500/20 px-2 py-1 text-[11px] font-semibold text-rose-200 disabled:opacity-40"
                          >
                            Confirm
                          </button>
                          <button
                            onClick={() => setConfirmId(null)}
                            className="text-[11px] text-slate-400 hover:text-slate-200"
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => setConfirmId(s.id)}
                          className="ml-auto text-[11px] text-slate-500 transition-colors hover:text-rose-300"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>

          {/* ---------------- Transaction ledger ---------------- */}
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <label className="sr-only" htmlFor="history-search">
                Search transactions
              </label>
              <input
                id="history-search"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setVisible(PAGE_SIZE);
                }}
                placeholder="Search description or category…"
                className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-teal-accent/50"
              />
              <label className="sr-only" htmlFor="history-category">
                Filter by category
              </label>
              <select
                id="history-category"
                value={category}
                onChange={(e) => {
                  setCategory(e.target.value);
                  setVisible(PAGE_SIZE);
                }}
                className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-2 text-sm text-slate-200 outline-none focus:border-teal-accent/50"
              >
                <option value="all">All categories</option>
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>

            <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
              <span>
                {filtered.length} of {txns.length} transactions
              </span>
              <span className="text-emerald-300">in {inr(totals.inc)}</span>
              <span className="text-orange-300">out {inr(totals.exp)}</span>
            </div>

            {loadingDetail ? (
              <p className="py-10 text-center text-sm text-slate-400">
                Loading transactions…
              </p>
            ) : filtered.length === 0 ? (
              <p className="py-10 text-center text-sm text-slate-400">
                {txns.length === 0
                  ? "This statement has no transactions."
                  : "Nothing matches that search."}
              </p>
            ) : (
              <>
                <div className="max-h-[28rem] overflow-y-auto rounded-xl border border-white/10">
                  <table className="w-full border-collapse text-left text-[12.5px]">
                    <thead className="sticky top-0 bg-navy-800/95 backdrop-blur">
                      <tr className="text-[11px] uppercase tracking-wider text-slate-400">
                        <th scope="col" className="px-3 py-2 font-semibold">
                          <button
                            onClick={() => toggleSort("date")}
                            className="transition-colors hover:text-slate-200"
                          >
                            Date {sortIndicator("date")}
                          </button>
                        </th>
                        <th scope="col" className="px-3 py-2 font-semibold">
                          Description
                        </th>
                        <th scope="col" className="px-3 py-2 font-semibold">
                          Category
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                          <button
                            onClick={() => toggleSort("amount")}
                            className="transition-colors hover:text-slate-200"
                          >
                            Amount {sortIndicator("amount")}
                          </button>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <AnimatePresence initial={false}>
                        {filtered.slice(0, visible).map((t, i) => (
                          <motion.tr
                            // Transactions have no id, so identity comes from the
                            // fields plus index (duplicates are legitimate).
                            key={`${t.date}-${t.description}-${t.amount}-${i}`}
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            className="border-t border-white/5 hover:bg-white/5"
                          >
                            <td className="whitespace-nowrap px-3 py-2 text-slate-400">
                              {shortDate(t.date)}
                            </td>
                            <td className="px-3 py-2 text-slate-200">
                              {t.description}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2">
                              <span
                                className="rounded px-1.5 py-0.5 text-[11px]"
                                style={{
                                  color: categoryColor(t.category),
                                  background: `${categoryColor(t.category)}1f`,
                                }}
                              >
                                {t.category || "Uncategorized"}
                              </span>
                            </td>
                            <td
                              className={`whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums ${
                                t.amount > 0 ? "text-emerald-300" : "text-slate-200"
                              }`}
                            >
                              {t.amount > 0 ? "+" : "−"}
                              {inr(Math.abs(t.amount))}
                            </td>
                          </motion.tr>
                        ))}
                      </AnimatePresence>
                    </tbody>
                  </table>
                </div>

                {visible < filtered.length && (
                  <button
                    onClick={() => setVisible((v) => v + PAGE_SIZE)}
                    className="mt-2 w-full rounded-lg border border-white/10 py-2 text-[12px] text-slate-300 transition-colors hover:bg-white/5"
                  >
                    Show {Math.min(PAGE_SIZE, filtered.length - visible)} more
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </GlassCard>
  );
}
