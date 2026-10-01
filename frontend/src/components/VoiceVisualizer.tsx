/**
 * Finzo's orb. Shows what the voice pipeline is doing at a glance.
 *
 * Live bars come from an AnalyserNode when one is available (microphone while
 * listening, playback while speaking). Without one, each state still has a
 * distinct CSS animation, so the UI never looks frozen. Honours
 * prefers-reduced-motion by dropping to static states.
 */
import { useEffect, useRef, useState } from "react";

export type VoiceUiState = "IDLE" | "LISTENING" | "PROCESSING" | "SPEAKING" | "ERROR";

interface Props {
  state: VoiceUiState;
  analyser?: AnalyserNode | null;
  size?: number;
}

const BARS = 5;

const TONE: Record<VoiceUiState, string> = {
  IDLE: "from-slate-500/40 to-slate-700/40 ring-white/10",
  LISTENING: "from-teal-400/70 to-emerald-500/50 ring-teal-300/40",
  PROCESSING: "from-violet-400/60 to-indigo-500/50 ring-violet-300/40",
  SPEAKING: "from-sky-400/70 to-teal-400/50 ring-sky-300/40",
  ERROR: "from-rose-500/60 to-rose-700/50 ring-rose-400/40",
};

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    setReduced(mq.matches);
    const on = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return reduced;
}

export default function VoiceVisualizer({ state, analyser, size = 72 }: Props) {
  const [levels, setLevels] = useState<number[]>(() => Array(BARS).fill(0.15));
  const raf = useRef<number>(0);
  const reduced = usePrefersReducedMotion();
  const live = !!analyser && (state === "LISTENING" || state === "SPEAKING") && !reduced;

  useEffect(() => {
    if (!live || !analyser) {
      setLevels(Array(BARS).fill(0.15));
      return;
    }
    const data = new Uint8Array(analyser.frequencyBinCount);
    let last = 0;
    const tick = (now: number) => {
      // ~30 fps is plenty for a level meter and halves the React work.
      if (now - last > 33) {
        last = now;
        analyser.getByteFrequencyData(data);
        const band = Math.floor(data.length / BARS);
        const next = Array.from({ length: BARS }, (_, i) => {
          let sum = 0;
          for (let j = i * band; j < (i + 1) * band; j++) sum += data[j];
          return Math.min(1, Math.max(0.12, sum / band / 160));
        });
        setLevels(next);
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [analyser, live]);

  const pulse = reduced
    ? ""
    : state === "IDLE"
      ? "animate-[pulse_4s_ease-in-out_infinite]"
      : state === "PROCESSING"
        ? "animate-spin [animation-duration:2.4s]"
        : state === "LISTENING" && !live
          ? "animate-pulse"
          : "";

  return (
    <div
      className="relative flex items-center justify-center"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <div
        className={`absolute inset-0 rounded-full bg-gradient-to-br ring-2 ${TONE[state]} ${pulse} transition-colors duration-300`}
      />
      {state === "PROCESSING" && !reduced && (
        <div className="absolute inset-1 rounded-full border-2 border-transparent border-t-violet-200/70 animate-spin" />
      )}
      <div className="relative flex h-1/2 items-center gap-[3px]">
        {state === "ERROR" ? (
          <span className="text-lg font-bold text-white">!</span>
        ) : (
          levels.map((lvl, i) => (
            <span
              key={i}
              className="w-[4px] rounded-full bg-white/85 transition-[height] duration-75"
              style={{
                height: `${Math.round(
                  (state === "PROCESSING" ? 0.35 : state === "IDLE" ? 0.2 : lvl) * 100
                )}%`,
              }}
            />
          ))
        )}
      </div>
    </div>
  );
}
