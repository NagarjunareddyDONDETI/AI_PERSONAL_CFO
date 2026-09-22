/**
 * Small animation building blocks shared by the marketing landing sections.
 *
 * Every one of these degrades to a static render when the global reduce-motion
 * toggle is on (see `src/lib/motion.tsx`). CSS-driven pieces get that for free
 * because `body.reduce-motion *` kills animations globally in index.css.
 */
import { ReactNode, useEffect, useRef, useState } from "react";
import { animate, motion, useInView } from "framer-motion";
import { useReduceMotion } from "../../lib/motion";

/** Shared easing — a soft overshoot-free ease-out used across the page. */
const EASE = [0.22, 1, 0.36, 1] as const;

interface RevealProps {
  children: ReactNode;
  /** Stagger offset in seconds. */
  delay?: number;
  /** Distance in px to travel upward into place. */
  y?: number;
  className?: string;
}

/** Fades and lifts its children into view the first time they are scrolled to. */
export function Reveal({ children, delay = 0, y = 26, className = "" }: RevealProps) {
  const { reduceMotion } = useReduceMotion();

  if (reduceMotion) return <div className={className}>{children}</div>;

  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.65, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

interface CountUpProps {
  to: number;
  suffix?: string;
  className?: string;
}

/**
 * Counts from zero to `to` once scrolled into view. Renders the final value
 * immediately under reduce-motion so the number is never missing.
 */
export function CountUp({ to, suffix = "", className = "" }: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const { reduceMotion } = useReduceMotion();
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (!inView) return;
    if (reduceMotion || to === 0) {
      setValue(to);
      return;
    }
    const controls = animate(0, to, {
      duration: 1.5,
      ease: "easeOut",
      onUpdate: (v) => setValue(Math.round(v)),
    });
    return () => controls.stop();
  }, [inView, to, reduceMotion]);

  return (
    <span ref={ref} className={className}>
      {value}
      {suffix}
    </span>
  );
}

interface MarqueeProps {
  items: string[];
}

/**
 * Infinite horizontal ticker. The track is rendered twice and translated by
 * -50%, which lands the second copy exactly where the first started — so the
 * loop has no visible seam.
 */
export function Marquee({ items }: MarqueeProps) {
  const track = [...items, ...items];

  return (
    <div
      aria-hidden="true"
      className="rail-mask relative overflow-hidden border-y border-white/5 bg-navy-950/70 py-4"
    >
      <div className="animate-marquee flex w-max items-center gap-3">
        {track.map((item, i) => (
          <span
            key={`${item}-${i}`}
            className="flex items-center gap-3 whitespace-nowrap text-[13px] font-medium tracking-wide text-slate-400"
          >
            {item}
            <span className="text-teal-accent/50">◆</span>
          </span>
        ))}
      </div>
    </div>
  );
}

interface SectionHeadingProps {
  eyebrow: string;
  title: ReactNode;
  intro?: string;
  /** Constrains the intro paragraph; sections in narrow columns want less. */
  className?: string;
}

/** Consistent eyebrow + headline + intro block used above each major section. */
export function SectionHeading({
  eyebrow,
  title,
  intro,
  className = "",
}: SectionHeadingProps) {
  return (
    <div className={className}>
      <Reveal>
        <p className="mb-3 flex items-center gap-2.5 text-[11px] font-semibold uppercase tracking-[0.2em] text-teal-accent">
          <span className="h-px w-8 bg-teal-accent/50" />
          {eyebrow}
        </p>
      </Reveal>
      <Reveal delay={0.06}>
        <h2 className="max-w-3xl text-3xl font-extrabold leading-[1.1] tracking-tight text-slate-50 md:text-5xl">
          {title}
        </h2>
      </Reveal>
      {intro && (
        <Reveal delay={0.12}>
          <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-slate-400">
            {intro}
          </p>
        </Reveal>
      )}
    </div>
  );
}
