/**
 * The Finzo hands-free loop.
 *
 * Wires the pieces together and owns every side effect:
 *
 *   wake word -> acknowledge -> record (VAD-gated) -> /voice/ask -> speak
 *             -> back to listening for a follow-up, no wake word needed
 *
 * The transition *rules* live in `voiceMachine.ts` as a pure reducer; this hook
 * only performs effects and dispatches. That split is what keeps the flow
 * reviewable, because the asynchronous parts here (permission, recognition, VAD,
 * upload, playback) can all complete out of order.
 *
 * Guarantees that matter:
 *   - The mic is only opened while a query is being captured. Idle listening runs
 *     entirely through the on-device recogniser and uploads nothing.
 *   - The recogniser is paused while our own TTS plays, so Finzo cannot trigger
 *     itself on its own voice.
 *   - Every failure path returns to a listening state; the loop never wedges.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { VoiceAskResult, voiceAsk, voiceAskStream } from "../api";
import { FinzoSettings } from "./finzoSettings";
import { Speaker, isSpeechOutputSupported } from "./speaker";
import { useVad } from "./useVad";
import { isWakeWordSupported, useWakeWord } from "./useWakeWord";
import {
  VoiceContext,
  initialVoiceContext,
  isConversationActive,
  shouldRunTimeout,
  voiceReducer,
} from "./voiceMachine";
import { isStopCommand } from "./wakeWord";

/** Local acknowledgements. Spoken via the Web Speech API so the "Yes?" is
 *  instant -- a server round trip just to say one word would defeat the point. */
const ACKS = ["Yes?", "I'm listening.", "Go ahead.", "How can I help?"];

function pickAck(): string {
  return ACKS[Math.floor(Math.random() * ACKS.length)];
}

function normalisePhrase(text: string): string {
  return text.trim().toLowerCase().replace(/[.,!?]+$/g, "");
}

const ACK_PHRASES = new Set(ACKS.map(normalisePhrase));

/**
 * Whether a heard phrase is just our own acknowledgement coming back.
 *
 * In fast mode the recogniser is deliberately left running while the "Yes?"
 * plays, because pausing it would mean missing the start of a user who answers
 * straight away. The cost is that the microphone sometimes hears the
 * acknowledgement, and it must not end up prefixed to the question.
 */
function isAckEcho(text: string): boolean {
  return ACK_PHRASES.has(normalisePhrase(text));
}

function pickMimeType(): string {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  for (const t of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t)) {
      return t;
    }
  }
  return "";
}

export interface FinzoTurn {
  role: "user" | "finzo";
  text: string;
  at: number;
}

interface Options {
  settings: FinzoSettings;
  /** Whether the account has an analysed statement; drives the NO_DATA hint. */
  hasData?: boolean;
}

export function useFinzo({ settings }: Options) {
  const [ctx, setCtx] = useState<VoiceContext>(initialVoiceContext);
  const [turns, setTurns] = useState<FinzoTurn[]>([]);
  const [micStream, setMicStream] = useState<MediaStream | null>(null);

  const dispatch = useCallback((event: Parameters<typeof voiceReducer>[1]) => {
    setCtx((current) => voiceReducer(current, event));
  }, []);

  // ---- refs for things effects must not re-create ------------------------- #
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const mimeRef = useRef("audio/webm");
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timeoutRef = useRef<number | null>(null);
  const stateRef = useRef(ctx.state);
  const settingsRef = useRef(settings);
  const busyRef = useRef(false);

  // What the on-device recogniser has heard since the current capture began.
  // Finalised phrases are appended; the still-changing phrase is held separately
  // so it can be replaced in place and then folded in when it finalises. The
  // engine frequently never finalises the last phrase before end-of-speech stops
  // it, so the interim text genuinely matters here.
  const heardFinalRef = useRef<string[]>([]);
  const heardInterimRef = useRef("");
  // Only collect while a query is actually being captured, so idle chatter and
  // the previous turn's answer never leak into the next question.
  const capturingRef = useRef(false);

  // One speech queue for the whole loop, so streamed sentences play in order.
  const speakerRef = useRef<Speaker | null>(null);
  if (speakerRef.current === null) speakerRef.current = new Speaker(settings);
  useEffect(() => {
    speakerRef.current?.updateSettings(settings);
  }, [settings]);

  const resetHeard = useCallback(() => {
    heardFinalRef.current = [];
    heardInterimRef.current = "";
  }, []);

  const collectHeard = useCallback((): string => {
    const parts = [...heardFinalRef.current, heardInterimRef.current];
    return parts
      .map((p) => p.trim())
      .filter(Boolean)
      .join(" ")
      .replace(/\s+/g, " ")
      .trim();
  }, []);

  useEffect(() => {
    stateRef.current = ctx.state;
  }, [ctx.state]);
  useEffect(() => {
    settingsRef.current = settings;
  }, [settings]);

  const active = settings.enabled && !settings.muted;
  const lowPower = settings.performanceMode === "low_cpu";

  // ---- microphone --------------------------------------------------------- #
  const releaseMic = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setMicStream(null);
  }, []);

  const openMic = useCallback(async (): Promise<MediaStream | null> => {
    if (streamRef.current) return streamRef.current;
    if (!navigator.mediaDevices?.getUserMedia) {
      dispatch({
        type: "UNSUPPORTED",
        message:
          window.isSecureContext === false
            ? "Microphone needs a secure page. Open the app via http://localhost:5173 or use HTTPS."
            : "This browser does not expose microphone access.",
      });
      return null;
    }
    try {
      const deviceId = settingsRef.current.microphoneId;
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
        },
      });
      streamRef.current = stream;
      setMicStream(stream);
      return stream;
    } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      const message =
        name === "NotAllowedError" || name === "SecurityError"
          ? "Microphone permission was blocked. Allow it in the address bar, then reload."
          : name === "NotFoundError"
            ? "No microphone was found."
            : name === "NotReadableError"
              ? "Your microphone is in use by another app."
              : "Microphone access failed.";
      dispatch({ type: "PERMISSION_DENIED", message });
      return null;
    }
  }, [dispatch]);

  // ---- playback ----------------------------------------------------------- #
  const stopPlayback = useCallback(() => {
    const el = audioRef.current;
    if (el) {
      el.pause();
      el.currentTime = 0;
    }
    speakerRef.current?.cancel();
  }, []);

  /**
   * Speak a line with the local voice, avoiding a network round trip.
   *
   * Goes through the shared queue so it cannot overlap streamed sentences, and so
   * barge-in cancels it along with everything else.
   */
  const speakLocally = useCallback(
    (text: string, intent?: string): Promise<void> => {
      const speaker = speakerRef.current;
      if (!speaker) return Promise.resolve();
      if (!speaker.enqueue(text, { intent })) return Promise.resolve();
      // Bounded: some engines never fire onend, and the loop must still resume
      // listening afterwards.
      return speaker.waitUntilIdle(Math.max(2500, text.length * 90));
    },
    []
  );

  const playMp3 = useCallback((base64: string): Promise<void> => {
    return new Promise((resolve) => {
      try {
        if (!audioRef.current) audioRef.current = new Audio();
        const el = audioRef.current;
        el.src = `data:audio/mpeg;base64,${base64}`;
        const done = () => resolve();
        el.onended = done;
        el.onerror = done;
        // Autoplay can be refused if no gesture has happened yet; falling
        // through means the answer is still on screen.
        el.play().catch(done);
      } catch {
        resolve();
      }
    });
  }, []);

  // ---- recording ---------------------------------------------------------- #
  const stopRecording = useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const rec = recorderRef.current;
      recorderRef.current = null;
      const collected = () =>
        chunksRef.current.length
          ? new Blob(chunksRef.current, { type: mimeRef.current })
          : null;

      let settled = false;
      const finish = (blob: Blob | null) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(guard);
        resolve(blob);
      };
      // This promise must always settle, or the machine sticks in TRANSCRIBING.
      const guard = window.setTimeout(() => finish(collected()), 2500);

      if (!rec || rec.state === "inactive") return finish(collected());
      rec.onstop = () => finish(collected());
      rec.onerror = () => finish(collected());
      try {
        rec.requestData?.();
        rec.stop();
      } catch {
        finish(collected());
      }
    });
  }, []);

  /**
   * Stop recording without waiting for the clip to be assembled.
   *
   * The fast path never uploads audio, so blocking on `onstop` (and its 2.5s
   * safety guard) would add latency for a blob that gets thrown away.
   */
  const discardRecording = useCallback(() => {
    const rec = recorderRef.current;
    recorderRef.current = null;
    chunksRef.current = [];
    if (!rec || rec.state === "inactive") return;
    rec.onstop = null;
    rec.onerror = null;
    rec.ondataavailable = null;
    try {
      rec.stop();
    } catch {
      /* already stopped */
    }
  }, []);

  const startRecording = useCallback(async (): Promise<boolean> => {
    const stream = await openMic();
    if (!stream) return false;
    chunksRef.current = [];
    const mime = pickMimeType();
    mimeRef.current = mime || "audio/webm";
    try {
      const rec = mime
        ? new MediaRecorder(stream, { mimeType: mime })
        : new MediaRecorder(stream);
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.start(250);
      recorderRef.current = rec;
      return true;
    } catch {
      dispatch({ type: "ERROR", message: "Could not start recording." });
      return false;
    }
  }, [dispatch, openMic]);

  // ---- the turn: streaming ------------------------------------------------ #
  /**
   * Streamed turn. Speaks each sentence as it arrives instead of waiting for the
   * whole answer, which is where most of the remaining latency was.
   *
   * Requires the local voice by definition: server-rendered MP3 cannot start
   * playing until synthesis has finished, so "streaming" and "server TTS" are
   * mutually exclusive.
   */
  const runStreamingTurn = useCallback(
    async (heard: string, blob: Blob | null, controller: AbortController) => {
      const speaker = speakerRef.current;
      const autoSpeak = settingsRef.current.autoSpeak;

      let answer = "";
      let intent: string | undefined;
      let failure: { message: string } | null = null;
      let stopped = false;
      let renderedAt = 0;

      // Repainting on every token is wasted work; the eye cannot follow it and it
      // competes with speech scheduling for the main thread.
      const render = (force = false) => {
        const now = Date.now();
        if (!force && now - renderedAt < 80) return;
        renderedAt = now;
        dispatch({ type: "PARTIAL_ANSWER", text: answer });
      };

      // Pause before the stream opens: the first sentence can start playing only
      // a few hundred milliseconds in, and Finzo must not hear itself.
      if (autoSpeak) pauseRecognitionRef.current?.();

      try {
        await voiceAskStream(blob, {
          transcript: heard || undefined,
          timeoutSeconds: settingsRef.current.conversationTimeout,
          signal: controller.signal,
          onMeta: (meta) => {
            intent = meta.intent;
            if (!heard && meta.transcript) {
              setTurns((t) => [
                ...t,
                { role: "user", text: meta.transcript, at: Date.now() },
              ]);
            }
          },
          onDelta: (text) => {
            answer += text;
            render();
          },
          onSpeak: (sentence) => {
            if (autoSpeak) speaker?.enqueue(sentence, { intent });
          },
          onAction: (action) => {
            if (action.action === "stop") {
              stopped = true;
              return;
            }
            // Bare wake word: the acknowledgement is all there is to say.
            if (action.speech && autoSpeak) {
              speaker?.enqueue(action.speech, { intent: "wake" });
            }
          },
          onDone: (done) => {
            answer = done.response || answer;
            intent = done.intent;
          },
          onError: (error) => {
            failure = { message: error.message };
          },
        });
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
      }

      if (controller.signal.aborted) return; // barge-in: nothing to report

      if (stopped) {
        stopPlayback();
        dispatch({ type: "INTERRUPT" });
        dispatch({ type: "PLAYBACK_DONE" });
        return;
      }

      if (failure) {
        const message = (failure as { message: string }).message;
        dispatch({ type: "ANSWER", text: message });
        setTurns((t) => [...t, { role: "finzo", text: message, at: Date.now() }]);
        if (autoSpeak) speaker?.enqueue(message);
      } else {
        answer = answer.trim();
        render(true);
        if (answer) {
          setTurns((t) => [...t, { role: "finzo", text: answer, at: Date.now() }]);
        }
      }

      // Let the queue finish before listening again, or Finzo would transcribe
      // the tail of its own answer as the next question.
      await speaker?.waitUntilIdle();
      resumeRecognitionRef.current?.();
      dispatch({ type: "PLAYBACK_DONE" });
    },
    [dispatch, stopPlayback]
  );

  // ---- the turn: one-shot (fallback) -------------------------------------- #
  /** The original single round trip. Used when streaming is off or unavailable. */
  const runOneShotTurn = useCallback(
    async (
      heard: string,
      blob: Blob | null,
      controller: AbortController,
      fast: boolean
    ) => {
      let result: VoiceAskResult;
      try {
        result = await voiceAsk(blob, {
          // Server-side TTS is a further round trip plus a base64 MP3 in the
          // response body. On the fast path the local voice starts speaking the
          // moment the text lands instead.
          speak: fast ? false : settingsRef.current.autoSpeak,
          transcript: heard || undefined,
          timeoutSeconds: settingsRef.current.conversationTimeout,
          signal: controller.signal,
        });
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
      }

      if (result.action === "stop") {
        stopPlayback();
        dispatch({ type: "INTERRUPT" });
        dispatch({ type: "PLAYBACK_DONE" });
        return;
      }

      // Only when the server did the transcribing. On the fast path we sent the
      // transcript ourselves and already showed it, so echoing it back would
      // duplicate the line.
      if (!heard && result.transcript) {
        setTurns((t) => [
          ...t,
          { role: "user", text: result.transcript, at: Date.now() },
        ]);
        dispatch({ type: "TRANSCRIBED", text: result.transcript });
      }

      const spoken = result.speech || result.error?.message || "";
      const written = result.response || spoken;
      if (written) {
        setTurns((t) => [...t, { role: "finzo", text: written, at: Date.now() }]);
      }
      dispatch({ type: "ANSWER", text: written });

      // Finzo must not hear itself: recognition is paused for the duration.
      pauseRecognitionRef.current?.();
      if (result.audio_b64) {
        await playMp3(result.audio_b64);
      } else if (spoken && settingsRef.current.autoSpeak) {
        // TTS unavailable server-side; the browser voice keeps it hands-free.
        await speakLocally(spoken, result.intent);
      }
      resumeRecognitionRef.current?.();

      dispatch({ type: "PLAYBACK_DONE" });
    },
    [dispatch, playMp3, speakLocally, stopPlayback]
  );

  // ---- the turn ----------------------------------------------------------- #
  const submitTurn = useCallback(async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    try {
      capturingRef.current = false;
      const fast = settingsRef.current.fastMode;
      // Read this before stopping anything: it is already complete, because the
      // recogniser transcribed while the user was talking.
      const heard = fast ? collectHeard() : "";

      let blob: Blob | null = null;
      if (heard) {
        // Fast path: the transcript is in hand, so the clip is dead weight.
        // Dropping it skips blob assembly, the upload, and Whisper on the server.
        discardRecording();
        releaseMic();
      } else {
        blob = await stopRecording();
        releaseMic();
        if (!blob || blob.size < 512) {
          // Too short to contain speech: quietly resume listening.
          dispatch({ type: "TIMEOUT" });
          return;
        }
      }

      // On the fast path the transcript is known now rather than after the round
      // trip, so it goes on screen immediately instead of a blank line.
      dispatch({ type: "TRANSCRIBED", text: heard });
      if (heard) {
        setTurns((t) => [...t, { role: "user", text: heard, at: Date.now() }]);
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      // Streaming speaks through the local voice, so it needs the browser to
      // support speech output at all.
      const streaming =
        settingsRef.current.streaming &&
        (!settingsRef.current.autoSpeak || isSpeechOutputSupported());

      try {
        if (streaming) {
          await runStreamingTurn(heard, blob, controller);
        } else {
          await runOneShotTurn(heard, blob, controller, fast);
        }
      } catch (e) {
        if (controller.signal.aborted) return; // barge-in: nothing to report
        resumeRecognitionRef.current?.();
        dispatch({
          type: "ERROR",
          message: e instanceof Error ? e.message : "Voice request failed.",
        });
      }
    } finally {
      busyRef.current = false;
    }
  }, [
    collectHeard,
    discardRecording,
    dispatch,
    releaseMic,
    runOneShotTurn,
    runStreamingTurn,
    stopRecording,
  ]);

  // ---- VAD drives the end of the query ------------------------------------ #
  const onSpeechEnd = useCallback(() => {
    if (stateRef.current !== "LISTENING_FOR_QUERY") return;
    dispatch({ type: "SPEECH_END" });
    void submitTurn();
  }, [dispatch, submitTurn]);

  const onMaxDuration = useCallback(() => {
    if (stateRef.current !== "LISTENING_FOR_QUERY") return;
    dispatch({ type: "SPEECH_END" });
    void submitTurn();
  }, [dispatch, submitTurn]);

  const { amplitude, speaking, reset: resetVad } = useVad(micStream, {
    onSpeechEnd,
    onMaxDuration,
    lowPower,
  });

  // ---- wake word ---------------------------------------------------------- #
  const pauseRecognitionRef = useRef<(() => void) | null>(null);
  const resumeRecognitionRef = useRef<(() => void) | null>(null);

  const beginQueryCapture = useCallback(async () => {
    resetVad();
    resetHeard();
    // Open the collector before the recorder: the recogniser is already running,
    // and a user who starts talking during getUserMedia should still be heard.
    capturingRef.current = true;
    const ok = await startRecording();
    if (!ok) {
      capturingRef.current = false;
      return;
    }
    dispatch({ type: "ACK_DONE" });
  }, [dispatch, resetHeard, resetVad, startRecording]);

  const onWake = useCallback(
    async (trailingQuery: string) => {
      // Wake word heard during playback is a barge-in.
      if (stateRef.current === "SPEAKING") {
        abortRef.current?.abort();
        stopPlayback();
        dispatch({ type: "INTERRUPT" });
      }
      if (busyRef.current) return;

      dispatch({ type: "WAKE_DETECTED", query: trailingQuery });

      const fast = settingsRef.current.fastMode;
      // Only acknowledge when the user has not already asked something.
      const wantAck = !trailingQuery && settingsRef.current.autoSpeak;

      // Normal mode keeps the original behaviour: mute the recogniser, say
      // "Yes?", and only then start listening. That is about three quarters of a
      // second of dead air, so fast mode instead starts capturing immediately and
      // lets the acknowledgement play over it (see below).
      if (wantAck && !fast) {
        pauseRecognitionRef.current?.();
        await speakLocally(pickAck());
        resumeRecognitionRef.current?.();
      }

      await beginQueryCapture();

      // A question asked in the same breath as the wake word was already heard,
      // so seed the collector with it rather than losing it.
      const trailing = trailingQuery.trim();
      if (trailing) heardFinalRef.current = [trailing];

      if (wantAck && fast) {
        // Deliberately not awaited, and the recogniser stays live so a user who
        // talks over the acknowledgement is still transcribed. isAckEcho() drops
        // the acknowledgement if the microphone picks it up.
        void speakLocally(pickAck());
      }
    },
    [beginQueryCapture, dispatch, speakLocally, stopPlayback]
  );

  /**
   * Accumulate what the recogniser hears during a capture.
   *
   * This is the whole basis of the fast path: by the time the user stops talking
   * the transcript already exists, so the turn can go straight to the LLM instead
   * of uploading audio and waiting for Whisper to produce the same words again.
   */
  const onTranscript = useCallback((text: string, isFinal: boolean) => {
    if (!capturingRef.current) return;
    const phrase = text.trim();
    if (!phrase || isAckEcho(phrase)) return;
    if (isFinal) {
      heardFinalRef.current = [...heardFinalRef.current, phrase];
      heardInterimRef.current = "";
    } else {
      // Interim results replace rather than append: the engine re-sends the whole
      // phrase as it refines it.
      heardInterimRef.current = phrase;
    }
  }, []);

  const onUtterance = useCallback(
    (text: string) => {
      // Barge-in by voice while Finzo is talking.
      if (stateRef.current === "SPEAKING" && isStopCommand(text)) {
        abortRef.current?.abort();
        stopPlayback();
        dispatch({ type: "INTERRUPT" });
        dispatch({ type: "PLAYBACK_DONE" });
      }
    },
    [dispatch, stopPlayback]
  );

  const onFatalError = useCallback(
    (message: string) => dispatch({ type: "UNSUPPORTED", message }),
    [dispatch]
  );

  const { listening, lastHeard, pause, resume, supported } = useWakeWord({
    // Recognition runs while idle AND during conversation, so "stop" and a
    // repeated wake word are both always audible.
    enabled: active && !ctx.unsupported,
    onWake,
    onUtterance,
    onTranscript,
    onFatalError,
    lowPower,
  });

  useEffect(() => {
    pauseRecognitionRef.current = pause;
    resumeRecognitionRef.current = resume;
  }, [pause, resume]);

  // ---- enable / disable --------------------------------------------------- #
  useEffect(() => {
    if (!settings.enabled) {
      dispatch({ type: "DISABLE" });
      stopPlayback();
      releaseMic();
      return;
    }
    if (settings.muted) {
      dispatch({ type: "DISABLE" });
      stopPlayback();
      releaseMic();
      return;
    }
    if (!isWakeWordSupported()) {
      dispatch({
        type: "UNSUPPORTED",
        message: "Hands-free voice is not supported in this browser.",
      });
      return;
    }
    dispatch({ type: "ENABLE" });
  }, [settings.enabled, settings.muted, dispatch, releaseMic, stopPlayback]);

  // ---- conversation timeout ---------------------------------------------- #
  useEffect(() => {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    const seconds = settings.conversationTimeout;
    if (seconds === 0 || !shouldRunTimeout(ctx.state)) return;

    timeoutRef.current = window.setTimeout(() => {
      timeoutRef.current = null;
      if (!shouldRunTimeout(stateRef.current)) return;
      // Nothing was asked, so discard what the recogniser heard rather than
      // letting it prefix the next question.
      capturingRef.current = false;
      resetHeard();
      // Drop the open mic; wake-word mode does not need it.
      void stopRecording();
      releaseMic();
      dispatch({ type: "TIMEOUT" });
    }, seconds * 1000);

    return () => {
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
    // ctx.revision so a fresh utterance restarts the countdown.
  }, [
    ctx.state,
    ctx.revision,
    settings.conversationTimeout,
    dispatch,
    releaseMic,
    resetHeard,
    stopRecording,
  ]);

  /**
   * Grant microphone permission from inside a user gesture, then release it.
   *
   * Chrome's SpeechRecognition will prompt for the microphone by itself, but a
   * prompt raised from a `useEffect` rather than a click is the flakiest path
   * through the permission model, and a dismissed prompt leaves the recogniser
   * silently dead. Asking during the enable click makes the grant explicit, and
   * it also unlocks device labels for the microphone picker.
   *
   * Returns true when the microphone is usable.
   */
  const primePermission = useCallback(async (): Promise<boolean> => {
    const stream = await openMic();
    if (!stream) return false;
    // Recognition opens its own capture; holding this one would double up.
    releaseMic();
    return true;
  }, [openMic, releaseMic]);

  // ---- manual controls (text fallback + explicit barge-in) --------------- #
  const interrupt = useCallback(() => {
    abortRef.current?.abort();
    stopPlayback();
    dispatch({ type: "INTERRUPT" });
    dispatch({ type: "PLAYBACK_DONE" });
  }, [dispatch, stopPlayback]);

  const recover = useCallback(() => dispatch({ type: "RECOVER" }), [dispatch]);

  /** Start a query without the wake word (button press). */
  const startManualQuery = useCallback(async () => {
    if (busyRef.current) return;
    dispatch({ type: "WAKE_DETECTED", query: "" });
    await beginQueryCapture();
  }, [beginQueryCapture, dispatch]);

  // ---- teardown ---------------------------------------------------------- #
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      stopPlayback();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
    };
  }, [stopPlayback]);

  return {
    state: ctx.state,
    transcript: ctx.transcript,
    answer: ctx.answer,
    error: ctx.error,
    unsupported: ctx.unsupported || !supported,
    turns,
    amplitude,
    userSpeaking: speaking,
    wakeListening: listening,
    lastHeard,
    micActive: micStream !== null,
    conversationActive: isConversationActive(ctx.state),
    interrupt,
    recover,
    startManualQuery,
    primePermission,
  };
}
