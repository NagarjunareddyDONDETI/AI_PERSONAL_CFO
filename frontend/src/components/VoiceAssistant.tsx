import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ApiError, Capabilities, sendChat, speak, transcribeAudio } from "../api";
import Markdown, { stripMarkdown } from "./Markdown";
import { useVoiceRecorder } from "../lib/useVoice";
import ErrorBoundary from "./ErrorBoundary";
import VoiceWaveCanvas from "./VoiceWaveCanvas";

type Status = "idle" | "listening" | "thinking" | "speaking";

// Without these the overlay can sit on "Thinking…" indefinitely: the chat call
// fans out to RAG plus an LLM with provider failover, so a stalled provider has
// no natural end. Better to fail with an explanation than to hang silently.
const STT_TIMEOUT_MS = 30_000;
const CHAT_TIMEOUT_MS = 60_000;

function withTimeout<T>(p: Promise<T>, ms: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), ms);
    p.then(
      (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      (e) => {
        clearTimeout(timer);
        reject(e);
      }
    );
  });
}

const STATUS_LABEL: Record<Status, string> = {
  idle: "Tap the mic and ask your question",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking…",
};

/**
 * Neon glowing microphone.
 *
 * Drawn on a 64-unit grid rather than the usual 24 so the capsule can carry a
 * grille and still land on crisp half-pixel edges at the 72px render size.
 *
 * The capsule is filled with the grille cut out of it in the backdrop colour —
 * a thin-stroke outline icon loses those details entirely once the neon glow
 * blooms over it, which is what made the previous version read as a smudge.
 */
function NeonMic({ active }: { active: boolean }) {
  const glow = active ? "#38bdf8" : "#22d3ee";
  return (
    <motion.svg
      width="72"
      height="72"
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      focusable="false"
      stroke={glow}
      strokeWidth="2.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      animate={active ? { scale: [1, 1.06, 1] } : { scale: 1 }}
      transition={{ duration: 1.4, repeat: active ? Infinity : 0, ease: "easeInOut" }}
      // Tighter than before: a 4px core plus a soft 14px halo at 40% keeps the
      // grille legible instead of drowning it in two full-strength shadows.
      style={{ filter: `drop-shadow(0 0 4px ${glow}) drop-shadow(0 0 14px ${glow}66)` }}
    >
      <defs>
        <linearGradient id="neonMicBody" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={glow} stopOpacity="1" />
          <stop offset="100%" stopColor={glow} stopOpacity="0.72" />
        </linearGradient>
      </defs>

      {/* Capsule */}
      <rect x="24" y="9" width="16" height="30" rx="8" fill="url(#neonMicBody)" stroke="none" />
      {/* Grille, knocked out of the capsule in the overlay's backdrop colour */}
      {[18, 23, 28, 33].map((y) => (
        <line
          key={y}
          x1="27.5"
          y1={y}
          x2="36.5"
          y2={y}
          stroke="#0a0e1a"
          strokeOpacity="0.55"
          strokeWidth="2"
        />
      ))}

      {/* Cradle — sweep-flag 0 arcs below the capsule, arms flanking it at
          x=18/46 so they clear the 24–40 capsule width. */}
      <path d="M18 31 A 14 14 0 0 0 46 31" />
      {/* Stand and base */}
      <line x1="32" y1="45" x2="32" y2="54" />
      <line x1="22" y1="54" x2="42" y2="54" />
    </motion.svg>
  );
}

export default function VoiceAssistant({
  capabilities,
  onClose,
}: {
  capabilities: Capabilities | null;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<Status>("idle");
  const [question, setQuestion] = useState<string>("");
  const [answer, setAnswer] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [meta, setMeta] = useState<{
    provider?: string;
    confidence?: number;
    latency?: number;
    lowConfidence?: boolean;
  } | null>(null);
  const voice = useVoiceRecorder();
  // A single, reusable <audio> element we "unlock" on the user gesture so the
  // browser's autoplay policy doesn't block playback after async awaits.
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      // Stop any ongoing speech when the overlay closes/unmounts.
      try {
        window.speechSynthesis?.cancel();
      } catch {
        /* ignore */
      }
      audioRef.current?.pause();
    };
  }, []);

  const active = status === "listening";

  // Unlock audio playback within a user gesture (muted play is always allowed).
  function unlockAudio() {
    if (!audioRef.current) audioRef.current = new Audio();
    const a = audioRef.current;
    a.muted = true;
    a.play().catch(() => {});
    a.pause();
    a.currentTime = 0;
    a.muted = false;
  }

  // Speak text: prefer natural server TTS (gTTS); fall back to the browser's
  // built-in speech synthesis so the assistant always talks back.
  async function speakResponse(markdown: string): Promise<void> {
    setStatus("speaking");
    const finish = () => setStatus("idle");
    // Speak the prose, not the syntax: TTS otherwise voices "asterisk asterisk"
    // around every bolded figure.
    const text = stripMarkdown(markdown);

    if (capabilities?.gtts) {
      try {
        const audioBlob = await speak(text);
        const url = URL.createObjectURL(audioBlob);
        const a = audioRef.current ?? new Audio();
        audioRef.current = a;
        a.src = url;
        a.onended = () => {
          URL.revokeObjectURL(url);
          finish();
        };
        await a.play();
        return; // playing successfully
      } catch {
        // Autoplay blocked or TTS failed — fall through to speechSynthesis.
      }
    }

    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      try {
        window.speechSynthesis.cancel();
        const utter = new SpeechSynthesisUtterance(text);
        utter.rate = 1.0;
        utter.pitch = 1.0;
        utter.onend = finish;
        utter.onerror = finish;
        window.speechSynthesis.speak(utter);
        return;
      } catch {
        /* ignore */
      }
    }
    finish(); // no TTS available — answer is still shown on screen
  }

  async function handleMic() {
    setError("");
    if (voice.recording) {
      // Unlock audio now, while we still have the user's tap gesture.
      unlockAudio();
      setStatus("thinking");
      const blob = await voice.stop();
      if (!blob || blob.size < 1200) {
        setStatus("idle");
        setError("That was too short. Tap the mic, wait a beat, then speak.");
        return;
      }
      try {
        let query = "";
        let sttError = "";
        try {
          const res = await withTimeout(
            transcribeAudio(blob),
            STT_TIMEOUT_MS,
            "Transcription timed out."
          );
          query = (res.text || "").trim();
          setMeta({
            provider: res.provider,
            confidence: res.confidence,
            latency: res.latency_ms,
            lowConfidence: res.low_confidence,
          });
        } catch (e) {
          // Fall back to the browser's live transcript, but remember why the
          // server failed — swallowing this left the user with no explanation.
          sttError = e instanceof Error ? e.message : "Transcription failed.";
          query = (voice.liveTranscript || "").trim();
          setMeta(null);
        }
        if (!query) query = (voice.liveTranscript || "").trim();
        if (!query) {
          setStatus("idle");
          setError(
            sttError
              ? `Couldn't transcribe that: ${sttError}`
              : "I couldn't make out any speech clearly. Please try again, a little louder and closer to the mic."
          );
          return;
        }
        setQuestion(query);
        setAnswer("");
        let res;
        try {
          res = await withTimeout(
            sendChat(query),
            CHAT_TIMEOUT_MS,
            "The assistant took too long to answer. Please try again."
          );
        } catch (e) {
          // Heard correctly but there is nothing to answer from. Say so out loud
          // rather than leaving the user in silence wondering if it heard them.
          const msg =
            e instanceof ApiError && e.status === 404
              ? "I heard you, but there's no statement loaded yet. Upload a bank statement first, then ask me again."
              : e instanceof Error
                ? e.message
                : "Something went wrong answering that.";
          setStatus("idle");
          setError(msg);
          await speakResponse(msg);
          return;
        }
        setAnswer(res.response);
        await speakResponse(res.response);
      } catch (e) {
        setStatus("idle");
        setError(
          e instanceof Error
            ? e.message
            : "Something went wrong processing your question."
        );
      }
    } else {
      setError("");
      setQuestion("");
      setAnswer("");
      setMeta(null);
      setStatus("listening");
      const startError = await voice.start();
      if (startError) {
        setStatus("idle");
        setError(startError);
      }
    }
  }

  return (
    <motion.div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center overflow-hidden"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      style={{
        background:
          "radial-gradient(circle at 50% 30%, #0b1e3a 0%, #060b1a 55%, #03060f 100%)",
      }}
    >
      {/* Animated sound-wave field fills the screen (2D canvas, crash-isolated) */}
      <div className="pointer-events-none absolute inset-0">
        <ErrorBoundary fallback={null}>
          <VoiceWaveCanvas amplitude={voice.amplitude} active={active} />
        </ErrorBoundary>
      </div>

      {/* Close button */}
      <button
        onClick={() => {
          if (voice.recording) voice.stop();
          try {
            window.speechSynthesis?.cancel();
          } catch {
            /* ignore */
          }
          audioRef.current?.pause();
          onClose();
        }}
        className="absolute right-5 top-5 z-10 rounded-full border border-white/15 bg-white/5 px-4 py-2 text-sm text-slate-200 backdrop-blur hover:bg-white/10 transition-colors"
      >
        ✕ Close
      </button>

      {/* Center content */}
      <div className="relative z-10 -mt-24 flex flex-col items-center px-6 text-center">
        {/* Pulsing halo behind the mic */}
        <div className="relative flex h-40 w-40 items-center justify-center">
          {active && (
            <>
              <motion.span
                className="absolute rounded-full border border-cyan-400/40"
                style={{ width: 120, height: 120 }}
                animate={{ scale: [1, 1.8], opacity: [0.5, 0] }}
                transition={{ duration: 1.8, repeat: Infinity, ease: "easeOut" }}
              />
              <motion.span
                className="absolute rounded-full border border-sky-400/30"
                style={{ width: 120, height: 120 }}
                animate={{ scale: [1, 2.4], opacity: [0.4, 0] }}
                transition={{ duration: 1.8, repeat: Infinity, ease: "easeOut", delay: 0.6 }}
              />
            </>
          )}
          <button
            onClick={handleMic}
            className="relative flex h-28 w-28 items-center justify-center rounded-full border border-cyan-400/30 bg-white/5 backdrop-blur transition-transform hover:scale-105"
            title={active ? "Tap to send" : "Tap to speak"}
          >
            <NeonMic active={active} />
          </button>
        </div>

        <p className="mt-8 text-lg font-medium text-cyan-100">
          {STATUS_LABEL[status]}
        </p>

        {/* Live indicators: provider · confidence · latency */}
        {meta && !voice.recording && (
          <div className="mt-2 flex flex-wrap items-center justify-center gap-2 text-[11px]">
            {meta.provider && (
              <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-slate-300">
                🎙 {meta.provider}
              </span>
            )}
            {typeof meta.confidence === "number" && (
              <span
                className="rounded-full px-2 py-0.5"
                style={{
                  background: meta.lowConfidence ? "#f59e0b22" : "#2dd4bf22",
                  color: meta.lowConfidence ? "#f59e0b" : "#2dd4bf",
                }}
              >
                {Math.round(meta.confidence * 100)}% confidence
              </span>
            )}
            {typeof meta.latency === "number" && meta.latency > 0 && (
              <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-slate-400">
                {Math.round(meta.latency)}ms
              </span>
            )}
          </div>
        )}
        {meta?.lowConfidence && !voice.recording && (
          <p className="mt-1 text-[11px] text-amber-300/80">
            Low confidence — tap the mic to repeat if this looks wrong.
          </p>
        )}

        {/* Live transcript while speaking */}
        <div className="mt-3 min-h-[2.5rem] max-w-xl">
          <AnimatePresence mode="wait">
            {voice.recording && voice.liveTranscript && (
              <motion.p
                key="live"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="text-xl italic text-white"
              >
                “{voice.liveTranscript}”
              </motion.p>
            )}
          </AnimatePresence>
        </div>

        {/* Recognized question */}
        <AnimatePresence>
          {question && !voice.recording && (
            <motion.p
              key="question"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mt-2 max-w-xl text-lg italic text-white/90"
            >
              “{question}”
            </motion.p>
          )}
        </AnimatePresence>

        {/* Assistant answer */}
        <AnimatePresence>
          {answer && !voice.recording && (
            <motion.div
              key="answer"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mt-4 max-w-xl rounded-2xl border border-white/10 bg-black/30 px-5 py-4 text-left text-sm leading-relaxed text-slate-100 backdrop-blur"
            >
              <Markdown text={answer} />
            </motion.div>
          )}
        </AnimatePresence>

        {error && (
          <p className="mt-4 max-w-md text-sm text-rose-300">{error}</p>
        )}

        {!(capabilities?.voice?.stt_providers?.length) && (
          <p className="mt-6 text-xs text-amber-300/80">
            No speech-to-text provider is available on the server — the live
            preview still works, but final answers may not. Set GROQ_API_KEY or
            install openai-whisper to enable transcription.
          </p>
        )}
      </div>
    </motion.div>
  );
}
