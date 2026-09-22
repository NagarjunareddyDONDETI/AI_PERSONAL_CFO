/**
 * Finzo voice state machine.
 *
 * A pure reducer: no audio, no timers, no React. The hands-free loop has enough
 * genuinely asynchronous parts (permission, recognition, VAD, upload, playback)
 * that keeping the *rules* separate from the effects is what makes the behaviour
 * reviewable and testable without a microphone.
 *
 * Transitions are whitelisted per state. An event that is not legal in the
 * current state is ignored rather than throwing, because these events come from
 * hardware and network callbacks that genuinely can arrive late — a `SPEECH_END`
 * landing after the user already said "stop" must not corrupt the state.
 */

export type VoiceState =
  | "IDLE"
  | "MIC_PERMISSION_REQUIRED"
  | "LISTENING_FOR_WAKE_WORD"
  | "WAKE_WORD_DETECTED"
  | "LISTENING_FOR_QUERY"
  | "TRANSCRIBING"
  | "THINKING"
  | "SPEAKING"
  | "INTERRUPTED"
  | "ERROR"
  | "DISABLED";

export type VoiceEvent =
  /** User turned the assistant on. */
  | { type: "ENABLE" }
  /** User turned it off, or hit mute. */
  | { type: "DISABLE" }
  | { type: "PERMISSION_REQUIRED" }
  | { type: "PERMISSION_GRANTED" }
  | { type: "PERMISSION_DENIED"; message: string }
  /** Browser cannot do hands-free at all (no SpeechRecognition / no mic API). */
  | { type: "UNSUPPORTED"; message: string }
  /** Wake phrase heard. `query` carries anything said in the same breath. */
  | { type: "WAKE_DETECTED"; query?: string }
  /** The short "Yes?" acknowledgement finished playing. */
  | { type: "ACK_DONE" }
  /** VAD detected the user starting to talk. */
  | { type: "SPEECH_START" }
  /** VAD detected trailing silence; the clip is being uploaded. */
  | { type: "SPEECH_END" }
  | { type: "TRANSCRIBED"; text: string }
  /** Answer received and about to be spoken. */
  | { type: "ANSWER"; text: string }
  /**
   * Answer text so far, while it is still streaming in.
   *
   * Separate from ANSWER because it arrives many times per turn and must be legal
   * from SPEAKING as well as THINKING: with streaming, speech starts on the first
   * sentence while later sentences are still being generated.
   */
  | { type: "PARTIAL_ANSWER"; text: string }
  | { type: "PLAYBACK_DONE" }
  /** Barge-in: "stop", or the wake word during playback. */
  | { type: "INTERRUPT" }
  /** Conversation-mode idle timeout elapsed. */
  | { type: "TIMEOUT" }
  | { type: "ERROR"; message: string }
  /** Recoverable error acknowledged; resume listening. */
  | { type: "RECOVER" };

export interface VoiceContext {
  state: VoiceState;
  /** Last transcript heard, for the on-screen transcript. */
  transcript: string;
  /** Last answer text. */
  answer: string;
  /** Human-readable problem, when state is ERROR or permission was denied. */
  error: string;
  /** True once the browser has been confirmed incapable of hands-free. */
  unsupported: boolean;
  /** Monotonic counter, bumped on every accepted transition. Lets effects key
   *  off "something actually changed" without deep-comparing context. */
  revision: number;
}

export const initialVoiceContext: VoiceContext = {
  state: "IDLE",
  transcript: "",
  answer: "",
  error: "",
  unsupported: false,
  revision: 0,
};

/**
 * Legal transitions. Events valid from ANY state are handled separately below,
 * so this table only describes the flow-specific moves.
 */
const TRANSITIONS: Record<VoiceState, Partial<Record<VoiceEvent["type"], VoiceState>>> = {
  IDLE: {
    ENABLE: "LISTENING_FOR_WAKE_WORD",
    PERMISSION_REQUIRED: "MIC_PERMISSION_REQUIRED",
  },
  MIC_PERMISSION_REQUIRED: {
    PERMISSION_GRANTED: "LISTENING_FOR_WAKE_WORD",
    ENABLE: "LISTENING_FOR_WAKE_WORD",
  },
  LISTENING_FOR_WAKE_WORD: {
    WAKE_DETECTED: "WAKE_WORD_DETECTED",
    PERMISSION_REQUIRED: "MIC_PERMISSION_REQUIRED",
  },
  WAKE_WORD_DETECTED: {
    // ACK_DONE is the normal path; SPEECH_START covers a user who talks straight
    // over the acknowledgement.
    ACK_DONE: "LISTENING_FOR_QUERY",
    SPEECH_START: "LISTENING_FOR_QUERY",
    // A wake phrase that already contained the question skips the prompt.
    TRANSCRIBED: "THINKING",
    TIMEOUT: "LISTENING_FOR_WAKE_WORD",
  },
  LISTENING_FOR_QUERY: {
    SPEECH_START: "LISTENING_FOR_QUERY",
    SPEECH_END: "TRANSCRIBING",
    // Wake word heard again mid-wait: treat as a fresh address, not an error.
    WAKE_DETECTED: "WAKE_WORD_DETECTED",
    TIMEOUT: "LISTENING_FOR_WAKE_WORD",
  },
  TRANSCRIBING: {
    TRANSCRIBED: "THINKING",
    // Empty/failed transcription is not fatal: go back to waiting.
    TIMEOUT: "LISTENING_FOR_QUERY",
  },
  THINKING: {
    ANSWER: "SPEAKING",
    // First streamed text doubles as the start of speaking.
    PARTIAL_ANSWER: "SPEAKING",
    TIMEOUT: "LISTENING_FOR_QUERY",
  },
  SPEAKING: {
    PLAYBACK_DONE: "LISTENING_FOR_QUERY",
    // Later chunks of a streaming answer; stays in SPEAKING.
    PARTIAL_ANSWER: "SPEAKING",
    ANSWER: "SPEAKING",
    // Barge-in while talking.
    INTERRUPT: "INTERRUPTED",
    WAKE_DETECTED: "INTERRUPTED",
  },
  INTERRUPTED: {
    // Interruption always lands back in conversation mode, so the user can
    // immediately say what they actually wanted.
    PLAYBACK_DONE: "LISTENING_FOR_QUERY",
    ACK_DONE: "LISTENING_FOR_QUERY",
    SPEECH_START: "LISTENING_FOR_QUERY",
    TIMEOUT: "LISTENING_FOR_WAKE_WORD",
  },
  ERROR: {
    RECOVER: "LISTENING_FOR_WAKE_WORD",
    ENABLE: "LISTENING_FOR_WAKE_WORD",
  },
  DISABLED: {
    ENABLE: "LISTENING_FOR_WAKE_WORD",
  },
};

/** States in which the microphone is actually open. Drives the privacy badge. */
export function isMicActive(state: VoiceState): boolean {
  return (
    state === "LISTENING_FOR_WAKE_WORD" ||
    state === "WAKE_WORD_DETECTED" ||
    state === "LISTENING_FOR_QUERY" ||
    state === "INTERRUPTED"
  );
}

/** True while a conversation is open, so follow-ups need no wake word. */
export function isConversationActive(state: VoiceState): boolean {
  return (
    state === "WAKE_WORD_DETECTED" ||
    state === "LISTENING_FOR_QUERY" ||
    state === "TRANSCRIBING" ||
    state === "THINKING" ||
    state === "SPEAKING" ||
    state === "INTERRUPTED"
  );
}

/** Whether the idle timeout should be running. */
export function shouldRunTimeout(state: VoiceState): boolean {
  return state === "LISTENING_FOR_QUERY" || state === "WAKE_WORD_DETECTED";
}

export function voiceReducer(ctx: VoiceContext, event: VoiceEvent): VoiceContext {
  const accept = (next: VoiceState, patch: Partial<VoiceContext> = {}): VoiceContext => ({
    ...ctx,
    ...patch,
    state: next,
    revision: ctx.revision + 1,
  });

  // ---- events legal from any state ---------------------------------------- #
  switch (event.type) {
    case "DISABLE":
      return accept("DISABLED", { transcript: "", answer: "", error: "" });
    case "UNSUPPORTED":
      return accept("DISABLED", { unsupported: true, error: event.message });
    case "PERMISSION_DENIED":
      return accept("MIC_PERMISSION_REQUIRED", { error: event.message });
    case "ERROR":
      return accept("ERROR", { error: event.message });
    default:
      break;
  }

  // A disabled assistant ignores everything except ENABLE, and stays disabled
  // outright if the browser cannot support it.
  if (ctx.state === "DISABLED" && event.type === "ENABLE" && ctx.unsupported) {
    return ctx;
  }

  const next = TRANSITIONS[ctx.state]?.[event.type];
  if (!next) return ctx; // illegal-in-this-state: ignore, never throw

  switch (event.type) {
    case "WAKE_DETECTED":
      return accept(next, {
        error: "",
        // Interrupting playback clears the stale answer; a fresh address does not.
        answer: next === "INTERRUPTED" ? "" : ctx.answer,
        transcript: event.query?.trim() ? event.query.trim() : "",
      });
    case "TRANSCRIBED":
      return accept(next, { transcript: event.text, error: "" });
    case "ANSWER":
    case "PARTIAL_ANSWER":
      return accept(next, { answer: event.text });
    case "ENABLE":
    case "RECOVER":
    case "PERMISSION_GRANTED":
      return accept(next, { error: "" });
    case "INTERRUPT":
      return accept(next, { answer: "" });
    default:
      return accept(next);
  }
}

/** Status line shown under the orb. */
export const STATUS_LABEL: Record<VoiceState, string> = {
  IDLE: "Voice assistant off",
  MIC_PERMISSION_REQUIRED: "Microphone access needed",
  LISTENING_FOR_WAKE_WORD: 'Listening for "Finzo"…',
  WAKE_WORD_DETECTED: "Yes?",
  LISTENING_FOR_QUERY: "I'm listening…",
  TRANSCRIBING: "Getting that down…",
  THINKING: "Thinking…",
  SPEAKING: "Speaking…",
  INTERRUPTED: "Stopped. Go ahead.",
  ERROR: "Something went wrong",
  DISABLED: "Voice assistant off",
};
