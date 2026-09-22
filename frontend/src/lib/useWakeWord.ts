/**
 * Continuous, on-device wake-word listening.
 *
 * Uses the browser's SpeechRecognition engine, which the project already relies
 * on for live interim transcripts in `useVoice.ts`. Two reasons this is the right
 * wake-word detector here rather than streaming audio frames to Whisper:
 *
 *   - It uploads NO audio to our backend while idle. The requirement is explicit
 *     about not continuously sending microphone audio to the server, and idle is
 *     where the assistant spends nearly all of its time.
 *   - Decoding audio frames through Whisper in a loop, purely to catch one word,
 *     costs far more CPU than a mid-range laptop should spend doing nothing.
 *
 * Whisper still handles the actual query, where accuracy matters.
 *
 * The engine stops itself frequently (on silence, on tab changes, on transient
 * network errors), so the bulk of this hook is keeping it alive without spinning.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { matchWakeWord } from "./wakeWord";

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onend: (() => void) | null;
};

function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

/** Whether hands-free is possible at all in this browser. */
export function isWakeWordSupported(): boolean {
  return getSpeechRecognitionCtor() !== null;
}

/** Errors that mean "never going to work", as opposed to "try again". */
const FATAL_ERRORS = new Set(["not-allowed", "service-not-allowed", "audio-capture"]);

/** Backoff bounds for restarting the recogniser. */
const RESTART_MIN_MS = 250;
const RESTART_MAX_MS = 4000;

interface Options {
  /** Master switch. When false the recogniser is fully torn down. */
  enabled: boolean;
  /** Called with any trailing query said in the same breath as the wake word. */
  onWake: (query: string) => void;
  /** Every finalised utterance, wake word or not. Used for barge-in detection. */
  onUtterance?: (text: string) => void;
  /**
   * Every phrase heard, interim or final, with its isFinal flag.
   *
   * This is what makes the low-latency path possible: the recogniser is already
   * transcribing the query as the user speaks, so the caller can collect that
   * text and skip uploading the clip for a second transcription. Interim results
   * are included because the engine often never finalises the last phrase before
   * we stop it at end of speech.
   */
  onTranscript?: (text: string, isFinal: boolean) => void;
  onFatalError?: (message: string) => void;
  /** Low-CPU mode: ignore interim results and only inspect final transcripts. */
  lowPower?: boolean;
  lang?: string;
}

export function useWakeWord({
  enabled,
  onWake,
  onUtterance,
  onTranscript,
  onFatalError,
  lowPower = false,
  lang = "en-US",
}: Options) {
  const [listening, setListening] = useState(false);
  const [lastHeard, setLastHeard] = useState("");

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const restartTimerRef = useRef<number | null>(null);
  const backoffRef = useRef(RESTART_MIN_MS);
  // Guards against the recogniser's async start/stop racing a teardown.
  const wantRunningRef = useRef(false);
  const startingRef = useRef(false);

  // Callbacks live in refs so changing them never tears down the recogniser --
  // re-creating it on every parent render would make it miss the wake word.
  const onWakeRef = useRef(onWake);
  const onUtteranceRef = useRef(onUtterance);
  const onTranscriptRef = useRef(onTranscript);
  const onFatalErrorRef = useRef(onFatalError);
  useEffect(() => {
    onWakeRef.current = onWake;
    onUtteranceRef.current = onUtterance;
    onTranscriptRef.current = onTranscript;
    onFatalErrorRef.current = onFatalError;
  }, [onWake, onUtterance, onTranscript, onFatalError]);

  const clearRestart = useCallback(() => {
    if (restartTimerRef.current !== null) {
      window.clearTimeout(restartTimerRef.current);
      restartTimerRef.current = null;
    }
  }, []);

  const teardown = useCallback(() => {
    wantRunningRef.current = false;
    clearRestart();
    const rec = recognitionRef.current;
    recognitionRef.current = null;
    if (rec) {
      rec.onresult = null;
      rec.onerror = null;
      rec.onend = null;
      try {
        rec.abort();
      } catch {
        /* already stopped */
      }
    }
    setListening(false);
  }, [clearRestart]);

  const startRecognition = useCallback(() => {
    if (!wantRunningRef.current || startingRef.current) return;
    if (recognitionRef.current) return;

    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) {
      onFatalErrorRef.current?.(
        "Hands-free voice is not supported in this browser."
      );
      return;
    }

    startingRef.current = true;
    let rec: SpeechRecognitionLike;
    try {
      rec = new Ctor();
    } catch {
      startingRef.current = false;
      onFatalErrorRef.current?.("Could not start speech recognition.");
      return;
    }

    rec.lang = lang;
    rec.continuous = true;
    rec.interimResults = !lowPower;
    rec.maxAlternatives = 1;

    rec.onresult = (event: unknown) => {
      const e = event as {
        resultIndex: number;
        results: ArrayLike<
          ArrayLike<{ transcript: string }> & { isFinal: boolean }
        >;
      };
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const result = e.results[i];
        const phrase = result[0]?.transcript ?? "";
        if (!phrase.trim()) continue;

        setLastHeard(phrase);
        onTranscriptRef.current?.(phrase, result.isFinal === true);
        if (result.isFinal) onUtteranceRef.current?.(phrase);

        // Interim results are checked too: waiting for the final transcript adds
        // most of a second before the assistant reacts, which is the difference
        // between feeling instant and feeling sluggish.
        const match = matchWakeWord(phrase);
        if (match.matched) {
          backoffRef.current = RESTART_MIN_MS;
          onWakeRef.current(match.query);
          return;
        }
      }
    };

    rec.onerror = (event: unknown) => {
      const code = (event as { error?: string }).error ?? "";
      if (FATAL_ERRORS.has(code)) {
        const message =
          code === "audio-capture"
            ? "No microphone was found."
            : "Microphone permission was blocked.";
        teardown();
        onFatalErrorRef.current?.(message);
        return;
      }
      // "no-speech" and "network" are routine; onend handles the restart.
    };

    rec.onend = () => {
      recognitionRef.current = null;
      setListening(false);
      if (!wantRunningRef.current) return;
      // Backoff stops a permanently-failing engine from becoming a busy loop.
      clearRestart();
      restartTimerRef.current = window.setTimeout(() => {
        restartTimerRef.current = null;
        startRecognition();
      }, backoffRef.current);
      backoffRef.current = Math.min(backoffRef.current * 2, RESTART_MAX_MS);
    };

    try {
      rec.start();
      recognitionRef.current = rec;
      setListening(true);
    } catch {
      // InvalidStateError: an engine is already running. onend will re-drive.
      recognitionRef.current = null;
    } finally {
      startingRef.current = false;
    }
  }, [clearRestart, lang, lowPower, teardown]);

  useEffect(() => {
    if (!enabled) {
      teardown();
      return;
    }
    if (!isWakeWordSupported()) {
      onFatalErrorRef.current?.(
        "Hands-free voice is not supported in this browser."
      );
      return;
    }
    wantRunningRef.current = true;
    backoffRef.current = RESTART_MIN_MS;
    startRecognition();
    return teardown;
  }, [enabled, lowPower, lang, startRecognition, teardown]);

  // The engine is silently killed when a tab is backgrounded; revive on return.
  useEffect(() => {
    if (!enabled) return;
    const onVisibility = () => {
      if (document.visibilityState === "visible" && wantRunningRef.current) {
        backoffRef.current = RESTART_MIN_MS;
        startRecognition();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [enabled, startRecognition]);

  /** Pause recognition while our own TTS plays, so Finzo cannot hear itself. */
  const pause = useCallback(() => {
    wantRunningRef.current = false;
    clearRestart();
    const rec = recognitionRef.current;
    if (rec) {
      try {
        rec.stop();
      } catch {
        /* ignore */
      }
    }
  }, [clearRestart]);

  const resume = useCallback(() => {
    if (!enabled) return;
    wantRunningRef.current = true;
    backoffRef.current = RESTART_MIN_MS;
    startRecognition();
  }, [enabled, startRecognition]);

  return { listening, lastHeard, pause, resume, supported: isWakeWordSupported() };
}
