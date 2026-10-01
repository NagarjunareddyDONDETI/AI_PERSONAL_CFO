/**
 * Push-to-talk Finzo: hold the button, ask, release, hear the answer.
 *
 * Sits next to the hands-free panel rather than replacing it. The two differ in
 * who starts listening: hands-free waits for "Hey Finzo", this waits for a press.
 * Both end in the same backend pipeline, so the answers are identical.
 *
 * Typing is always available underneath; voice is an extra way in.
 */
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  FinzoVoiceChatResult,
  FinzoVoiceHealth,
  HandsFreeStatus,
  getFinzoVoiceHealth,
  getHandsFreeStatus,
} from "../api";
import { AnswerPlayer, MicError, PushToTalkRecorder, askFinzo } from "../services/finzoVoice";
import GlassCard from "./GlassCard";
import VoiceVisualizer, { VoiceUiState } from "./VoiceVisualizer";

interface Props {
  delay?: number;
}

const STATUS_TEXT: Record<VoiceUiState, string> = {
  IDLE: "Hold to talk",
  LISTENING: "Listening… release when you're done",
  PROCESSING: "Thinking…",
  SPEAKING: "Finzo",
  ERROR: "Something went wrong",
};

const HANDSFREE_LABEL: Record<string, string> = {
  LISTENING_FOR_WAKE_WORD: 'Say "Hey Finzo"',
  WAKE_DETECTED: "Heard you",
  LISTENING: "Listening…",
  TRANSCRIBING: "Getting that down…",
  THINKING: "Thinking…",
  SPEAKING: "Speaking",
  INTERRUPTED: "Stopped",
  ERROR: "Needs attention",
  IDLE: "Off",
};

function friendlyError(e: unknown): string {
  if (e instanceof MicError) return e.message;
  if (e instanceof ApiError) {
    if (e.status === 429) return "That's a lot of questions at once. Give it a moment and try again.";
    if (e.status === 413) return "That recording was too long. Try a shorter question.";
    if (e.status >= 500) return "Finzo's server had a problem. Please try again.";
  }
  if (e instanceof TypeError) return "Couldn't reach the Finzo server. Check that the backend is running.";
  return "Sorry, that didn't work. Please try again.";
}

export default function FinzoVoiceButton({ delay = 0 }: Props) {
  const [ui, setUi] = useState<VoiceUiState>("IDLE");
  const [error, setError] = useState("");
  const [transcript, setTranscript] = useState("");
  const [answer, setAnswer] = useState("");
  const [lastAudio, setLastAudio] = useState<{ b64: string; mime?: string | null } | null>(null);
  const [needsTap, setNeedsTap] = useState(false);
  const [typed, setTyped] = useState("");
  const [health, setHealth] = useState<FinzoVoiceHealth | null>(null);
  const [handsFree, setHandsFree] = useState<HandsFreeStatus | null>(null);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);

  const recorderRef = useRef<PushToTalkRecorder | null>(null);
  const playerRef = useRef<AnswerPlayer | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Press/release can outrun getUserMedia; remember a release that came early.
  const startingRef = useRef(false);
  const releasedEarlyRef = useRef(false);

  const player = () => (playerRef.current ??= new AnswerPlayer());

  // ---- provider health + hands-free status (polled, cheap) --------------- #
  useEffect(() => {
    let alive = true;
    getFinzoVoiceHealth()
      .then((h) => alive && setHealth(h))
      .catch(() => alive && setHealth(null));
    const poll = () =>
      getHandsFreeStatus()
        .then((s) => alive && setHandsFree(s))
        .catch(() => alive && setHandsFree(null));
    poll();
    const id = window.setInterval(poll, 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      recorderRef.current?.release();
      playerRef.current?.dispose();
    },
    []
  );

  // ---- the turn ------------------------------------------------------------ #
  const speak = useCallback(async (audio: { b64: string; mime?: string | null }) => {
    setUi("SPEAKING");
    setAnalyser(player().analyser);
    try {
      await player().play(audio.b64, audio.mime);
    } catch {
      // Autoplay refused. The answer is on screen; offer a tap to hear it.
      setNeedsTap(true);
    } finally {
      setAnalyser(null);
      setUi("IDLE");
    }
  }, []);

  const runTurn = useCallback(
    async (input: { audio?: Blob | null; transcript?: string }) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setUi("PROCESSING");
      setError("");
      setNeedsTap(false);
      let result: FinzoVoiceChatResult;
      try {
        result = await askFinzo(input, controller.signal);
      } catch (e) {
        if (controller.signal.aborted) return;
        setError(friendlyError(e));
        setUi("ERROR");
        return;
      }
      if (result.action === "stop") {
        setUi("IDLE");
        return;
      }
      if (result.transcript) setTranscript(result.transcript);
      const text = result.response || result.speech || result.error?.message || "";
      setAnswer(text);
      if (!result.ok && result.error) setError(result.error.message);

      if (result.audio_b64) {
        const audio = { b64: result.audio_b64, mime: result.audio_mime };
        setLastAudio(audio);
        await speak(audio);
      } else {
        setLastAudio(null);
        setUi(result.ok ? "IDLE" : "ERROR");
      }
    },
    [speak]
  );

  // ---- push-to-talk ---------------------------------------------------- #
  const pressStart = useCallback(async () => {
    if (ui === "PROCESSING" || startingRef.current || recorderRef.current) return;
    // Talking over Finzo interrupts it.
    player().stop();
    abortRef.current?.abort();
    setError("");
    releasedEarlyRef.current = false;
    startingRef.current = true;

    const rec = new PushToTalkRecorder();
    try {
      await rec.start();
    } catch (e) {
      startingRef.current = false;
      rec.release();
      setError(friendlyError(e));
      setUi("ERROR");
      return;
    }
    startingRef.current = false;
    recorderRef.current = rec;
    setAnalyser(rec.analyser);
    setUi("LISTENING");
    rec.onAutoStop = () => void pressEnd();
    if (releasedEarlyRef.current) void pressEnd();
    // pressEnd is stable enough here; it reads refs, not state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ui]);

  const pressEnd = useCallback(async () => {
    if (startingRef.current) {
      releasedEarlyRef.current = true;
      return;
    }
    const rec = recorderRef.current;
    if (!rec) return;
    recorderRef.current = null;
    setAnalyser(null);
    const recording = await rec.stop();
    if (!recording) {
      setUi("IDLE");
      setError("That was too short. Hold the button while you ask.");
      return;
    }
    await runTurn({ audio: recording.blob });
  }, [runTurn]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.key === " " || e.key === "Enter") && !e.repeat) {
      e.preventDefault();
      void pressStart();
    }
  };
  const onKeyUp = (e: React.KeyboardEvent) => {
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      void pressEnd();
    }
  };

  const onTypedSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = typed.trim();
    if (!q || ui === "PROCESSING") return;
    setTranscript(q);
    setTyped("");
    void runTurn({ transcript: q });
  };

  const voicebox = health?.voicebox;
  const voiceboxLabel = !health
    ? "Checking voice services…"
    : voicebox?.ok
      ? voicebox.config?.voice_id_configured
        ? "Voicebox connected"
        : "Voicebox connected, no voice profile set"
      : `Voicebox offline, using ${health.tts_providers[0] ?? "no"} voice`;

  return (
    <GlassCard title="Finzo voice" subtitle="Push to talk. Answers use your real statement data." delay={delay}>
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
        <button
          type="button"
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture?.(e.pointerId);
            void pressStart();
          }}
          onPointerUp={() => void pressEnd()}
          onPointerCancel={() => void pressEnd()}
          onKeyDown={onKeyDown}
          onKeyUp={onKeyUp}
          onContextMenu={(e) => e.preventDefault()}
          disabled={ui === "PROCESSING"}
          aria-pressed={ui === "LISTENING"}
          aria-label={ui === "LISTENING" ? "Release to send your question" : "Hold to ask Finzo"}
          className="shrink-0 touch-none select-none rounded-full outline-none focus-visible:ring-2 focus-visible:ring-teal-accent focus-visible:ring-offset-2 focus-visible:ring-offset-navy-900 disabled:cursor-wait"
        >
          <VoiceVisualizer state={ui} analyser={analyser} size={84} />
        </button>

        <div className="min-w-0 flex-1 space-y-2 text-center sm:text-left">
          <p className="text-sm font-medium text-slate-100" aria-live="polite">
            {STATUS_TEXT[ui]}
          </p>
          <p className="text-[11px] text-slate-500">
            {voiceboxLabel}
            {handsFree?.running && (
              <>
                {" · "}Hands-free: {HANDSFREE_LABEL[handsFree.state] ?? handsFree.state}
              </>
            )}
          </p>

          {error && (
            <p role="alert" className="rounded-lg bg-rose-500/10 px-3 py-2 text-[12px] text-rose-200">
              {error}
            </p>
          )}

          {transcript && (
            <p className="text-[13px] text-slate-400">
              <span className="text-slate-500">You: </span>
              {transcript}
            </p>
          )}
          {answer && (
            <p className="whitespace-pre-line text-[13px] leading-relaxed text-slate-100">
              <span className="text-teal-accent">Finzo: </span>
              {answer}
            </p>
          )}
          {lastAudio && ui === "IDLE" && (
            <button
              type="button"
              onClick={() => void speak(lastAudio)}
              className="rounded-lg bg-white/5 px-2.5 py-1 text-[11px] text-slate-300 hover:bg-white/10"
            >
              {needsTap ? "Tap to hear the answer" : "Play again"}
            </button>
          )}
        </div>
      </div>

      <form onSubmit={onTypedSubmit} className="mt-4 flex gap-2">
        <label htmlFor="finzo-voice-typed" className="sr-only">
          Or type your question
        </label>
        <input
          id="finzo-voice-typed"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder="Or type: How much did I spend on food this month?"
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-[13px] text-slate-200 outline-none placeholder:text-slate-500 focus:border-teal-accent/50"
        />
        <button
          type="submit"
          disabled={!typed.trim() || ui === "PROCESSING"}
          className="rounded-lg bg-teal-accent px-3 py-2 text-[12px] font-medium text-navy-900 disabled:opacity-40"
        >
          Ask
        </button>
      </form>
    </GlassCard>
  );
}
