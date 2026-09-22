/**
 * The Finzo orb.
 *
 * Each voice state gets a visually distinct treatment, so the assistant's status
 * is readable at a glance without reading the label underneath -- which matters
 * for a hands-free interface, where the user is often not looking directly at the
 * screen when they start talking.
 *
 * All motion is gated on the app's reduce-motion preference.
 */
import { motion } from "framer-motion";
import { VoiceState } from "../lib/voiceMachine";
import { useReduceMotion } from "../lib/motion";

interface Props {
  state: VoiceState;
  /** Live input level 0-1, used while listening. */
  amplitude: number;
  size?: number;
}

/** Per-state palette. Teal = ready, violet = working, rose = problem. */
const TONE: Record<VoiceState, { ring: string; glow: string }> = {
  IDLE: { ring: "#475569", glow: "rgba(71,85,105,0.25)" },
  DISABLED: { ring: "#475569", glow: "rgba(71,85,105,0.25)" },
  MIC_PERMISSION_REQUIRED: { ring: "#fbbf24", glow: "rgba(251,191,36,0.35)" },
  LISTENING_FOR_WAKE_WORD: { ring: "#2dd4bf", glow: "rgba(45,212,191,0.28)" },
  WAKE_WORD_DETECTED: { ring: "#2dd4bf", glow: "rgba(45,212,191,0.55)" },
  LISTENING_FOR_QUERY: { ring: "#38bdf8", glow: "rgba(56,189,248,0.5)" },
  TRANSCRIBING: { ring: "#a78bfa", glow: "rgba(167,139,250,0.45)" },
  THINKING: { ring: "#a78bfa", glow: "rgba(167,139,250,0.5)" },
  SPEAKING: { ring: "#2dd4bf", glow: "rgba(45,212,191,0.55)" },
  INTERRUPTED: { ring: "#94a3b8", glow: "rgba(148,163,184,0.3)" },
  ERROR: { ring: "#fb7185", glow: "rgba(251,113,133,0.4)" },
};

export default function FinzoOrb({ state, amplitude, size = 132 }: Props) {
  const { reduceMotion } = useReduceMotion();
  const tone = TONE[state];

  const listening = state === "LISTENING_FOR_QUERY";
  const waiting = state === "LISTENING_FOR_WAKE_WORD";
  const working = state === "THINKING" || state === "TRANSCRIBING";
  const speaking = state === "SPEAKING";
  const woke = state === "WAKE_WORD_DETECTED";

  // While listening the orb tracks the user's actual voice level, so it is
  // obvious the microphone is picking them up.
  const level = listening ? 1 + amplitude * 0.22 : 1;

  return (
    <div
      className="relative flex items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Finzo voice status: ${state.toLowerCase().replace(/_/g, " ")}`}
    >
      {/* Outer halo: a slow breath while waiting, wider once addressed. */}
      <motion.span
        aria-hidden="true"
        className="absolute rounded-full"
        style={{
          width: size,
          height: size,
          background: `radial-gradient(circle, ${tone.glow} 0%, transparent 70%)`,
        }}
        animate={
          reduceMotion
            ? { opacity: 0.6, scale: 1 }
            : waiting
              ? { opacity: [0.35, 0.7, 0.35], scale: [0.92, 1, 0.92] }
              : woke
                ? { opacity: 0.9, scale: 1.08 }
                : { opacity: 0.75, scale: 1 }
        }
        transition={
          reduceMotion
            ? { duration: 0 }
            : waiting
              ? { duration: 3.2, repeat: Infinity, ease: "easeInOut" }
              : { duration: 0.4 }
        }
      />

      {/* Concentric rings, pushed outward when speaking. */}
      {[0.72, 0.86].map((scale, i) => (
        <motion.span
          key={scale}
          aria-hidden="true"
          className="absolute rounded-full border"
          style={{
            width: size * scale,
            height: size * scale,
            borderColor: tone.ring,
            opacity: 0.25,
          }}
          animate={
            reduceMotion || !speaking
              ? { scale: 1, opacity: 0.25 }
              : { scale: [1, 1.12, 1], opacity: [0.3, 0.08, 0.3] }
          }
          transition={
            reduceMotion || !speaking
              ? { duration: 0.3 }
              : { duration: 1.5, repeat: Infinity, delay: i * 0.35, ease: "easeOut" }
          }
        />
      ))}

      {/* Core */}
      <motion.span
        aria-hidden="true"
        className="relative flex items-center justify-center rounded-full border"
        style={{
          width: size * 0.54,
          height: size * 0.54,
          borderColor: tone.ring,
          background:
            "radial-gradient(circle at 35% 30%, rgba(255,255,255,0.10), rgba(6,9,18,0.9))",
          boxShadow: `0 0 24px ${tone.glow}`,
        }}
        animate={reduceMotion ? { scale: 1 } : { scale: level }}
        transition={{ type: "spring", stiffness: 260, damping: 22 }}
      >
        {/* Waveform while listening: five bars driven by input level. */}
        {listening && !reduceMotion ? (
          <span className="flex items-end gap-[3px]" aria-hidden="true">
            {[0.5, 0.8, 1, 0.75, 0.45].map((weight, i) => (
              <motion.span
                key={i}
                className="w-[3px] rounded-full"
                style={{ background: tone.ring }}
                animate={{
                  height: Math.max(4, amplitude * 26 * weight + 4),
                }}
                transition={{ type: "spring", stiffness: 320, damping: 18 }}
              />
            ))}
          </span>
        ) : working && !reduceMotion ? (
          // Rotating arc while transcribing/thinking.
          <motion.span
            className="rounded-full border-2 border-transparent"
            style={{
              width: size * 0.3,
              height: size * 0.3,
              borderTopColor: tone.ring,
              borderRightColor: tone.ring,
            }}
            animate={{ rotate: 360 }}
            transition={{ duration: 1.1, repeat: Infinity, ease: "linear" }}
          />
        ) : (
          <span
            className="text-[15px] font-bold tracking-tight"
            style={{ color: tone.ring }}
            aria-hidden="true"
          >
            {state === "ERROR" ? "!" : state === "MIC_PERMISSION_REQUIRED" ? "?" : "F"}
          </span>
        )}
      </motion.span>
    </div>
  );
}
