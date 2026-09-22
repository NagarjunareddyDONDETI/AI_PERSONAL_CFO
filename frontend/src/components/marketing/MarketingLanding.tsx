/**
 * Public marketing landing page — the first thing a signed-out visitor sees.
 *
 * Structure borrows from Netflix's careers site: a full-bleed hero with the art
 * running under a transparent nav, then horizontally scrolling "rows" of cards,
 * big typographic statement blocks, and a dense link footer. The palette stays
 * on this app's own identity (teal + violet on near-black navy) rather than
 * Netflix red, so the page and the dashboard feel like one product.
 *
 * Not to be confused with `components/Landing.tsx`, which is the authenticated
 * statement-upload screen shown after sign-in.
 */
import { Suspense, lazy, useRef } from "react";
import { motion, useScroll, useSpring, useTransform } from "framer-motion";
import { useReduceMotion } from "../../lib/motion";
import ErrorBoundary from "../ErrorBoundary";
import CardRail from "./CardRail";
import MarketingNav from "./MarketingNav";
import { CountUp, Marquee, Reveal, SectionHeading } from "./motionPrimitives";
import {
  ANALYSIS_CARDS,
  FOOTER_COLUMNS,
  INTELLIGENCE_CARDS,
  MARQUEE_ITEMS,
  PRIVACY_POINTS,
  STATS,
  STEPS,
} from "./data";

// Reuses the dashboard's 3D hero scene as moving hero art instead of shipping a
// separate background asset. Code-split and skipped entirely under reduce-motion.
const HeroScene = lazy(() => import("../../three/HeroScene"));

const HEADLINE_WORDS = ["A", "CFO", "for", "a", "company", "of", "one."];

/** Receipts for the explainability claim — each maps to a field on /explain. */
const EXPLAIN_FIELDS = [
  "the reasoning",
  "the formula",
  "the transactions used",
  "the documents retrieved",
  "a confidence level",
  "the model that answered",
];

interface Props {
  /** Opens the auth screen on the "create account" tab. */
  onGetStarted: () => void;
  /** Opens the auth screen on the "sign in" tab. */
  onSignIn: () => void;
}

export default function MarketingLanding({ onGetStarted, onSignIn }: Props) {
  const { reduceMotion } = useReduceMotion();
  const stepsRef = useRef<HTMLOListElement>(null);

  // Page-wide read-progress bar.
  const { scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, { stiffness: 120, damping: 30, mass: 0.3 });

  // Hero parallax: content drifts up and fades while the art pushes in slightly.
  const { scrollY } = useScroll();
  const contentY = useTransform(scrollY, [0, 700], [0, 130]);
  const contentOpacity = useTransform(scrollY, [0, 460], [1, 0]);
  const sceneScale = useTransform(scrollY, [0, 700], [1, 1.12]);

  // Fills the timeline spine as the steps section passes through the viewport.
  const { scrollYProgress: stepsProgress } = useScroll({
    target: stepsRef,
    offset: ["start 75%", "end 65%"],
  });
  const spineScale = useSpring(stepsProgress, { stiffness: 90, damping: 26 });

  return (
    <div id="top" className="relative bg-navy-900">
      {/* Scroll progress indicator — omitted entirely under reduce-motion, where
          a permanently-animating bar would be the exact thing being opted out of. */}
      {!reduceMotion && (
        <motion.div
          aria-hidden="true"
          style={{ scaleX: progress }}
          className="fixed inset-x-0 top-0 z-[60] h-0.5 origin-left bg-gradient-to-r from-teal-accent via-violet-accent to-teal-accent"
        />
      )}

      <MarketingNav onGetStarted={onGetStarted} onSignIn={onSignIn} />

      {/* ------------------------------------------------------------------ */}
      {/* Hero                                                                */}
      {/* ------------------------------------------------------------------ */}
      <section className="relative flex min-h-[100svh] items-center overflow-hidden">
        {!reduceMotion && (
          <motion.div style={{ scale: sceneScale }} className="absolute inset-0 z-0">
            <ErrorBoundary fallback={null}>
              <Suspense fallback={null}>
                <HeroScene />
              </Suspense>
            </ErrorBoundary>
          </motion.div>
        )}
        {reduceMotion && <div className="ambient-bg absolute inset-0 z-0" />}

        {/* Scrim keeps headline contrast over the moving art and blends the
            hero into the section below. */}
        <div aria-hidden="true" className="hero-scrim absolute inset-0 z-10" />
        <div
          aria-hidden="true"
          className="blueprint-grid absolute inset-0 z-10 opacity-40"
        />

        <motion.div
          style={reduceMotion ? undefined : { y: contentY, opacity: contentOpacity }}
          className="relative z-20 mx-auto w-full max-w-7xl px-6 pb-24 pt-32 md:px-10"
        >
          <motion.p
            initial={reduceMotion ? undefined : { opacity: 0, y: 12 }}
            animate={reduceMotion ? undefined : { opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="mb-6 flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.28em] text-teal-accent"
          >
            <span className="h-px w-10 bg-teal-accent/60" />
            AI Personal CFO
          </motion.p>

          {/* Each word sits in its own clipping box and slides up from below —
              the space between words stays outside those boxes so it is never
              clipped mid-animation. */}
          <h1 className="max-w-4xl text-[2.75rem] font-extrabold leading-[0.98] tracking-[-0.02em] text-slate-50 sm:text-6xl md:text-7xl lg:text-[5.25rem]">
            {HEADLINE_WORDS.map((word, i) => (
              <span key={`${word}-${i}`}>
                <span className="inline-block overflow-hidden pb-1 align-bottom">
                  <motion.span
                    initial={reduceMotion ? undefined : { y: "105%" }}
                    animate={reduceMotion ? undefined : { y: 0 }}
                    transition={{
                      duration: 0.85,
                      delay: 0.15 + i * 0.075,
                      ease: [0.22, 1, 0.36, 1],
                    }}
                    className={`inline-block ${
                      word === "one." ? "gradient-text animate-gradientPan" : ""
                    }`}
                  >
                    {word}
                  </motion.span>
                </span>
                {i < HEADLINE_WORDS.length - 1 && " "}
              </span>
            ))}
          </h1>

          <motion.p
            initial={reduceMotion ? undefined : { opacity: 0, y: 16 }}
            animate={reduceMotion ? undefined : { opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.75 }}
            className="mt-7 max-w-xl text-[15px] leading-relaxed text-slate-300 md:text-[17px]"
          >
            Drop in a bank statement and get categorised spending, anomaly alerts,
            a next-month forecast, a financial health score, and an advisor you can
            argue with — every figure showing the working behind it.
          </motion.p>

          <motion.div
            initial={reduceMotion ? undefined : { opacity: 0, y: 16 }}
            animate={reduceMotion ? undefined : { opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.88 }}
            className="mt-9 flex flex-wrap items-center gap-3"
          >
            <button
              type="button"
              onClick={onGetStarted}
              className="focus-ring group relative overflow-hidden rounded-xl bg-gradient-to-r from-teal-accent to-violet-accent px-7 py-3.5 text-sm font-bold text-navy-900 transition-transform hover:scale-[1.03]"
            >
              <span className="relative z-10">Analyse my statement</span>
              {/* Sheen sweep on hover */}
              <span
                aria-hidden="true"
                className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/40 to-transparent transition-transform duration-700 group-hover:translate-x-full"
              />
            </button>
            <button
              type="button"
              onClick={onSignIn}
              className="focus-ring rounded-xl border border-white/20 bg-white/5 px-7 py-3.5 text-sm font-semibold text-slate-100 backdrop-blur transition-colors hover:border-teal-accent/50 hover:bg-white/10"
            >
              Sign in
            </button>
          </motion.div>

          <motion.p
            initial={reduceMotion ? undefined : { opacity: 0 }}
            animate={reduceMotion ? undefined : { opacity: 1 }}
            transition={{ duration: 0.7, delay: 1 }}
            className="mt-6 text-[12.5px] text-slate-500"
          >
            CSV, Excel, JSON or PDF — or load a bundled sample and look around first.
          </motion.p>
        </motion.div>

        <div
          aria-hidden="true"
          className="absolute bottom-7 left-1/2 z-20 -translate-x-1/2 text-center"
        >
          <span className="animate-scrollCue block text-lg text-slate-500">↓</span>
        </div>
      </section>

      <Marquee items={MARQUEE_ITEMS} />

      {/* ------------------------------------------------------------------ */}
      {/* Stats                                                               */}
      {/* ------------------------------------------------------------------ */}
      <section className="border-b border-white/5 bg-navy-900 py-16 md:py-20">
        <div className="mx-auto grid max-w-7xl grid-cols-2 gap-x-6 gap-y-10 px-6 md:grid-cols-4 md:px-10">
          {STATS.map((stat, i) => (
            <Reveal key={stat.label} delay={i * 0.08}>
              <p className="text-4xl font-extrabold tracking-tight text-teal-accent md:text-5xl">
                <CountUp to={stat.value} suffix={stat.suffix} />
              </p>
              <p className="mt-2 text-[13px] font-semibold text-slate-200">
                {stat.label}
              </p>
              <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
                {stat.note}
              </p>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Rail 1 — automatic analysis                                         */}
      {/* ------------------------------------------------------------------ */}
      <section id="capabilities" className="scroll-mt-24 bg-navy-900 py-20 md:py-28">
        <div className="mx-auto mb-12 max-w-7xl px-6 md:px-10">
          <SectionHeading
            eyebrow="On upload"
            title={
              <>
                Everything below happens
                <br className="hidden sm:block" /> before you ask for it.
              </>
            }
            intro="One statement in. Categorisation, scoring, anomaly detection and a forecast out — no dashboards to configure, no rules to write, no tagging by hand."
          />
        </div>
        <CardRail cards={ANALYSIS_CARDS} label="Analysis capabilities" />
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* How it works                                                        */}
      {/* ------------------------------------------------------------------ */}
      <section
        id="how-it-works"
        className="scroll-mt-24 border-y border-white/5 bg-navy-950 py-20 md:py-28"
      >
        <div className="mx-auto max-w-7xl px-6 md:px-10">
          <SectionHeading
            eyebrow="How it works"
            title="Three steps, then you are just asking questions."
          />

          <ol ref={stepsRef} className="relative mt-14 max-w-3xl">
            {/* Timeline spine: a dim track with a bright fill that grows on scroll. */}
            <span
              aria-hidden="true"
              className="absolute left-[1.4rem] top-2 hidden h-[calc(100%-2rem)] w-px bg-white/10 sm:block"
            />
            <motion.span
              aria-hidden="true"
              style={{ scaleY: reduceMotion ? 1 : spineScale }}
              className="absolute left-[1.4rem] top-2 hidden h-[calc(100%-2rem)] w-px origin-top bg-gradient-to-b from-teal-accent to-violet-accent sm:block"
            />

            {STEPS.map((step, i) => (
              <li key={step.index} className="relative pb-12 last:pb-0 sm:pl-20">
                <Reveal delay={i * 0.1}>
                  <span className="absolute left-0 top-0 hidden h-11 w-11 items-center justify-center rounded-full border border-white/15 bg-navy-800 text-[13px] font-bold text-teal-accent sm:flex">
                    {step.index}
                  </span>
                  <p className="mb-2 text-[11px] font-semibold tracking-[0.2em] text-teal-accent sm:hidden">
                    {step.index}
                  </p>
                  <h3 className="text-xl font-bold text-slate-50 md:text-2xl">
                    {step.title}
                  </h3>
                  <p className="mt-2.5 max-w-xl text-[14.5px] leading-relaxed text-slate-400">
                    {step.body}
                  </p>
                </Reveal>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Rail 2 — the reasoning layer                                        */}
      {/* ------------------------------------------------------------------ */}
      <section id="intelligence" className="scroll-mt-24 bg-navy-900 py-20 md:py-28">
        <div className="mx-auto mb-12 max-w-7xl px-6 md:px-10">
          <SectionHeading
            eyebrow="Intelligence"
            title="Where it stops reporting and starts advising."
            intro="Ask in plain language or out loud, make several advisors disagree in front of you, then simulate the decision before you commit to it."
          />
        </div>
        <CardRail cards={INTELLIGENCE_CARDS} label="Intelligence capabilities" />
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Explainability statement                                            */}
      {/* ------------------------------------------------------------------ */}
      <section
        id="explainability"
        className="relative scroll-mt-24 overflow-hidden border-y border-white/5 bg-navy-950 py-24 md:py-32"
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -left-32 top-1/2 h-[28rem] w-[28rem] -translate-y-1/2 rounded-full bg-teal-accent/10 blur-[110px]"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -right-32 top-1/3 h-[26rem] w-[26rem] rounded-full bg-violet-accent/10 blur-[110px]"
        />

        <div className="relative mx-auto max-w-4xl px-6 text-center md:px-10">
          <Reveal>
            <p className="mb-6 text-[11px] font-semibold uppercase tracking-[0.28em] text-violet-accent">
              Explainability
            </p>
          </Reveal>
          <Reveal delay={0.06}>
            <h2 className="text-3xl font-extrabold leading-[1.12] tracking-tight text-slate-50 md:text-5xl">
              Most money tools hand you a number
              <br className="hidden md:block" />{" "}
              <span className="text-slate-500">and expect you to trust it.</span>
            </h2>
          </Reveal>
          <Reveal delay={0.14}>
            <p className="mx-auto mt-7 max-w-2xl text-[15px] leading-relaxed text-slate-400 md:text-[17px]">
              Here, every figure opens. Tap into any score, forecast or
              recommendation and you get the whole chain behind it:
            </p>
          </Reveal>

          <div className="mt-9 flex flex-wrap justify-center gap-2.5">
            {EXPLAIN_FIELDS.map((field, i) => (
              <Reveal key={field} delay={0.2 + i * 0.06}>
                <span className="glass inline-flex items-center gap-2 rounded-full px-4 py-2 text-[13px] text-slate-200">
                  <span aria-hidden="true" className="text-teal-accent">
                    ✦
                  </span>
                  {field}
                </span>
              </Reveal>
            ))}
          </div>

          <Reveal delay={0.6}>
            <p className="mx-auto mt-10 max-w-xl text-[13.5px] leading-relaxed text-slate-500">
              And when no model key is configured, it says so and falls back to
              computed values — rather than quietly inventing an answer.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Trust                                                               */}
      {/* ------------------------------------------------------------------ */}
      <section id="trust" className="scroll-mt-24 bg-navy-900 py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-6 md:px-10">
          <SectionHeading
            eyebrow="Trust"
            title="Your statements are nobody else's business."
          />
          <div className="mt-14 grid gap-5 md:grid-cols-3">
            {PRIVACY_POINTS.map((point, i) => (
              <Reveal key={point.title} delay={i * 0.1}>
                <div className="glass h-full rounded-2xl p-6 transition-colors hover:border-teal-accent/30">
                  <span
                    aria-hidden="true"
                    className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-navy-950/60 text-lg text-teal-accent"
                  >
                    {point.glyph}
                  </span>
                  <h3 className="text-[17px] font-bold text-slate-50">
                    {point.title}
                  </h3>
                  <p className="mt-2 text-[13.5px] leading-relaxed text-slate-400">
                    {point.body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Closing CTA                                                         */}
      {/* ------------------------------------------------------------------ */}
      <section className="relative overflow-hidden border-t border-white/5 bg-navy-950 py-24 md:py-32">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute left-1/2 top-0 h-[30rem] w-[42rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-gradient-to-r from-teal-accent/15 to-violet-accent/15 blur-[120px]"
        />
        <div className="relative mx-auto max-w-3xl px-6 text-center md:px-10">
          <Reveal>
            <h2 className="text-3xl font-extrabold leading-[1.1] tracking-tight text-slate-50 md:text-[3.25rem]">
              One statement is all it takes
              <br className="hidden sm:block" />{" "}
              <span className="gradient-text animate-gradientPan">to find out.</span>
            </h2>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="mx-auto mt-6 max-w-lg text-[15px] leading-relaxed text-slate-400">
              Create an account, upload a statement, and read the whole picture in
              the time it takes to make coffee.
            </p>
          </Reveal>
          <Reveal delay={0.18}>
            <div className="mt-10 flex flex-wrap justify-center gap-3">
              <button
                type="button"
                onClick={onGetStarted}
                className="focus-ring group relative overflow-hidden rounded-xl bg-gradient-to-r from-teal-accent to-violet-accent px-8 py-3.5 text-sm font-bold text-navy-900 transition-transform hover:scale-[1.03]"
              >
                <span className="relative z-10">Create your account</span>
                <span
                  aria-hidden="true"
                  className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/40 to-transparent transition-transform duration-700 group-hover:translate-x-full"
                />
              </button>
              <button
                type="button"
                onClick={onSignIn}
                className="focus-ring rounded-xl border border-white/20 px-8 py-3.5 text-sm font-semibold text-slate-100 transition-colors hover:border-teal-accent/50 hover:bg-white/5"
              >
                I already have one
              </button>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Footer                                                              */}
      {/* ------------------------------------------------------------------ */}
      <footer className="border-t border-white/5 bg-navy-950 px-6 py-16 md:px-10">
        <div className="mx-auto max-w-7xl">
          <div className="mb-12 flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-accent to-teal-accent text-base font-extrabold text-navy-900">
              ₹
            </span>
            <div>
              <p className="text-[15px] font-bold leading-tight text-slate-100">
                AI Personal CFO
              </p>
              <p className="text-[11px] leading-tight text-slate-500">
                Your finances, explained.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-6 gap-y-10 md:grid-cols-4">
            {FOOTER_COLUMNS.map((column) => (
              <div key={column.heading}>
                <h3 className="mb-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  {column.heading}
                </h3>
                <ul className="space-y-2.5">
                  {column.links.map((link) => (
                    <li key={link.label}>
                      <a
                        href={`#${link.target}`}
                        className="focus-ring text-[13px] text-slate-400 transition-colors hover:text-teal-accent"
                      >
                        {link.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mt-14 flex flex-col gap-4 border-t border-white/5 pt-7 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[12px] text-slate-600">
              Self-hosted. Your statements stay on your own server.
            </p>
            <button
              type="button"
              onClick={onGetStarted}
              className="focus-ring self-start text-[12.5px] font-semibold text-teal-accent transition-opacity hover:opacity-75 sm:self-auto"
            >
              Get started →
            </button>
          </div>
        </div>
      </footer>
    </div>
  );
}
