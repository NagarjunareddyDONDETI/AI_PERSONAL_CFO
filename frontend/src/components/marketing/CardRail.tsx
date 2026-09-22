/**
 * Horizontally scrolling row of capability cards — the "show row" pattern from
 * Netflix's site, adapted to this app's palette.
 *
 * Behaviour worth preserving:
 *  - arrows page the rail by ~80% of the visible width and hide at each end
 *  - cards lift and reveal a longer description on hover or keyboard focus
 *  - the artwork panel contracts as that description expands, so card height
 *    never changes and the row does not reflow while you scan it
 *  - the rail is a focusable scroll region so it can be paged with the keyboard
 *  - card detail text stays in the DOM (visually clipped, not display:none) so
 *    screen readers always get the full description
 */
import { useCallback, useEffect, useRef, useState } from "react";
import CardArt from "./CardArt";
import { RailCard } from "./data";
import { useReduceMotion } from "../../lib/motion";

interface Props {
  cards: RailCard[];
  /** Accessible name for the scroll region, e.g. "Analysis capabilities". */
  label: string;
}

export default function CardRail({ cards, label }: Props) {
  const scrollerRef = useRef<HTMLUListElement>(null);
  const { reduceMotion } = useReduceMotion();
  const [atStart, setAtStart] = useState(true);
  const [atEnd, setAtEnd] = useState(false);

  const syncEdges = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    // 4px of slack absorbs sub-pixel scroll positions from smooth scrolling.
    setAtStart(el.scrollLeft <= 4);
    setAtEnd(el.scrollLeft + el.clientWidth >= el.scrollWidth - 4);
  }, []);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    syncEdges();
    el.addEventListener("scroll", syncEdges, { passive: true });
    window.addEventListener("resize", syncEdges);
    return () => {
      el.removeEventListener("scroll", syncEdges);
      window.removeEventListener("resize", syncEdges);
    };
  }, [syncEdges]);

  function page(direction: -1 | 1) {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollBy({
      left: direction * Math.max(280, el.clientWidth * 0.8),
      behavior: reduceMotion ? "auto" : "smooth",
    });
  }

  return (
    <div className="group/rail relative">
      <ul
        ref={scrollerRef}
        tabIndex={0}
        role="group"
        aria-label={label}
        className="no-scrollbar focus-ring flex snap-x snap-mandatory gap-4 overflow-x-auto scroll-smooth px-6 pb-4 md:px-16"
      >
        {cards.map((card) => (
          <li
            key={card.id}
            tabIndex={0}
            className="group/card focus-ring relative flex h-[21rem] w-[16.5rem] shrink-0 snap-start flex-col overflow-hidden rounded-2xl border border-white/10 bg-navy-800/70 p-5 transition-all duration-500 ease-out hover:-translate-y-1.5 hover:border-teal-accent/40 hover:bg-navy-700/80 hover:shadow-[0_18px_50px_-12px_rgba(45,212,191,0.28)] focus-within:-translate-y-1.5 focus-within:border-teal-accent/40 sm:w-[18rem]"
          >
            {/* Background wash — the per-card tint, intensifying on hover. */}
            <span
              aria-hidden="true"
              className={`pointer-events-none absolute inset-0 bg-gradient-to-br opacity-70 transition-opacity duration-500 group-hover/card:opacity-100 ${card.tint}`}
            />

            <div className="relative flex h-full flex-col">
              {/* Artwork previews what the feature renders in the dashboard. It
                  contracts on hover to free up room for the detail copy below,
                  which keeps the card's overall height constant. */}
              <div className="relative mb-4 h-32 shrink-0 overflow-hidden rounded-xl border border-white/5 bg-navy-950/40 transition-[height] duration-500 ease-out group-hover/card:h-24 group-focus-within/card:h-24">
                <div className="absolute inset-0 transition-transform duration-700 ease-out group-hover/card:scale-[1.06]">
                  <CardArt id={card.id} />
                </div>
                <span
                  aria-hidden="true"
                  className="absolute left-2.5 top-2.5 flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 bg-navy-950/75 text-[13px] text-teal-accent backdrop-blur-sm"
                >
                  {card.glyph}
                </span>
              </div>

              {/* Absorbs slack so the detail block has somewhere to expand into. */}
              <div className="min-h-0 flex-1" />

              <h3 className="text-[17px] font-bold leading-snug text-slate-50">
                {card.title}
              </h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-slate-300">
                {card.blurb}
              </p>

              <p className="max-h-0 overflow-hidden text-[12.5px] leading-relaxed text-slate-400 opacity-0 transition-all duration-500 ease-out group-hover/card:mt-3 group-hover/card:max-h-44 group-hover/card:opacity-100 group-focus-within/card:mt-3 group-focus-within/card:max-h-44 group-focus-within/card:opacity-100">
                {card.detail}
              </p>
            </div>
          </li>
        ))}
      </ul>

      {/* Paging arrows: pointer affordance only — the rail itself is keyboard
          scrollable, and touch users swipe. Hidden when there is nowhere to go. */}
      <button
        type="button"
        onClick={() => page(-1)}
        aria-label={`Scroll ${label} backward`}
        className={`absolute left-3 top-[10.5rem] hidden h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/15 bg-navy-950/80 text-slate-200 backdrop-blur transition-all hover:scale-110 hover:border-teal-accent/50 hover:text-teal-accent md:flex ${
          atStart ? "pointer-events-none opacity-0" : "opacity-70 group-hover/rail:opacity-100"
        }`}
      >
        <span aria-hidden="true">‹</span>
      </button>
      <button
        type="button"
        onClick={() => page(1)}
        aria-label={`Scroll ${label} forward`}
        className={`absolute right-3 top-[10.5rem] hidden h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/15 bg-navy-950/80 text-slate-200 backdrop-blur transition-all hover:scale-110 hover:border-teal-accent/50 hover:text-teal-accent md:flex ${
          atEnd ? "pointer-events-none opacity-0" : "opacity-70 group-hover/rail:opacity-100"
        }`}
      >
        <span aria-hidden="true">›</span>
      </button>
    </div>
  );
}
