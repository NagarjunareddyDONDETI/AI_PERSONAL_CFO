import { motion } from "framer-motion";

export const PAGES = [
  { id: "overview", label: "Overview", icon: "◍" },
  { id: "insights", label: "Insights", icon: "◆" },
  { id: "history", label: "History", icon: "◷" },
  { id: "planning", label: "Planning", icon: "◈" },
  { id: "advisor", label: "Advisor", icon: "◉" },
  { id: "memory", label: "Memory", icon: "◎" },
] as const;

export type PageId = (typeof PAGES)[number]["id"];
export const PAGE_IDS = PAGES.map((p) => p.id) as readonly PageId[];

/**
 * Sticky tab bar. Sits directly under the app header and stays visible while a
 * page scrolls, so switching views never requires scrolling back up — the main
 * complaint with the previous single-page layout.
 */
export default function PageNav({
  active,
  onNavigate,
}: {
  active: PageId;
  onNavigate: (id: PageId) => void;
}) {
  return (
    <nav
      aria-label="Sections"
      className="sticky top-0 z-30 border-b border-white/10 bg-navy-900/80 backdrop-blur"
    >
      <div className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 md:px-6">
        {PAGES.map((page) => {
          const selected = page.id === active;
          return (
            <button
              key={page.id}
              onClick={() => onNavigate(page.id)}
              aria-current={selected ? "page" : undefined}
              className={`relative shrink-0 px-3.5 py-3 text-sm transition-colors md:px-4 ${
                selected
                  ? "text-slate-100"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span className="mr-1.5 text-[11px] opacity-70">{page.icon}</span>
              {page.label}
              {selected && (
                <motion.span
                  layoutId="page-nav-underline"
                  className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-gradient-to-r from-teal-accent to-violet-accent"
                  transition={{ type: "spring", stiffness: 420, damping: 34 }}
                />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
