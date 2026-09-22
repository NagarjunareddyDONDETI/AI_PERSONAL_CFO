/**
 * Sticky marketing nav. Transparent over the hero, then morphs into a solid
 * glass bar once you scroll past it — the same trick Netflix's site uses so the
 * hero art is never boxed in by chrome.
 */
import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { NAV_SECTIONS } from "./data";
import { useReduceMotion } from "../../lib/motion";

interface Props {
  onSignIn: () => void;
  onGetStarted: () => void;
}

export default function MarketingNav({ onSignIn, onGetStarted }: Props) {
  const { reduceMotion } = useReduceMotion();
  const [solid, setSolid] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setSolid(window.scrollY > 40);
    onScroll(); // account for a restored scroll position on reload
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  function jumpTo(id: string) {
    setMenuOpen(false);
    document.getElementById(id)?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "start",
    });
  }

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-all duration-500 ${
        solid
          ? "border-b border-white/10 bg-navy-950/85 backdrop-blur-xl"
          : "border-b border-transparent bg-gradient-to-b from-navy-950/70 to-transparent"
      }`}
    >
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 md:px-10">
        <a
          href="#top"
          onClick={(e) => {
            e.preventDefault();
            window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
          }}
          className="focus-ring flex items-center gap-3"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-accent to-teal-accent text-base font-extrabold text-navy-900">
            ₹
          </span>
          <span className="text-[15px] font-bold tracking-tight text-slate-50">
            AI Personal CFO
          </span>
        </a>

        <nav aria-label="Sections" className="hidden items-center gap-1 lg:flex">
          {NAV_SECTIONS.map((section) => (
            <button
              key={section.id}
              type="button"
              onClick={() => jumpTo(section.id)}
              className="focus-ring rounded-lg px-3.5 py-2 text-[13px] font-medium text-slate-300 transition-colors hover:text-teal-accent"
            >
              {section.label}
            </button>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onSignIn}
            className="focus-ring rounded-xl px-3.5 py-2 text-[13px] font-semibold text-slate-200 transition-colors hover:text-teal-accent"
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={onGetStarted}
            className="focus-ring rounded-xl bg-gradient-to-r from-teal-accent to-violet-accent px-4 py-2 text-[13px] font-bold text-navy-900 transition-transform hover:scale-[1.04]"
          >
            Get started
          </button>
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            aria-expanded={menuOpen}
            aria-label="Toggle section menu"
            className="focus-ring ml-1 rounded-lg border border-white/10 px-2.5 py-2 text-slate-300 lg:hidden"
          >
            <span aria-hidden="true">{menuOpen ? "✕" : "☰"}</span>
          </button>
        </div>
      </div>

      <AnimatePresence>
        {menuOpen && (
          <motion.nav
            aria-label="Sections"
            initial={reduceMotion ? undefined : { height: 0, opacity: 0 }}
            animate={reduceMotion ? undefined : { height: "auto", opacity: 1 }}
            exit={reduceMotion ? undefined : { height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
            className="overflow-hidden border-t border-white/10 bg-navy-950/95 lg:hidden"
          >
            <div className="flex flex-col px-6 py-2">
              {NAV_SECTIONS.map((section) => (
                <button
                  key={section.id}
                  type="button"
                  onClick={() => jumpTo(section.id)}
                  className="focus-ring border-b border-white/5 py-3 text-left text-sm font-medium text-slate-300 last:border-0 hover:text-teal-accent"
                >
                  {section.label}
                </button>
              ))}
            </div>
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  );
}
