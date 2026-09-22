/**
 * Persisted Finzo preferences.
 *
 * Stored in localStorage rather than the database on purpose: these are
 * per-device choices. Whether the microphone should be live, and whether this
 * machine can afford full-rate audio analysis, are properties of the device in
 * front of the user, not of their account.
 *
 * `enabled` defaults to FALSE. An always-on microphone must be an explicit,
 * deliberate opt-in -- never something that silently activates on load.
 */

export type PerformanceMode = "standard" | "low_cpu";

export interface FinzoSettings {
  /** Master switch for hands-free listening. Opt-in. */
  enabled: boolean;
  /** Temporarily suspend the mic without forgetting the opt-in. */
  muted: boolean;
  /** Seconds of silence before conversation mode ends. 0 = never. */
  conversationTimeout: number;
  /** Speak answers aloud. When false, answers appear as text only. */
  autoSpeak: boolean;
  /** Reduces wake-word sampling and visualisation work. */
  performanceMode: PerformanceMode;
  /** Chosen input device, or "" for the system default. */
  microphoneId: string;
  /**
   * Low-latency path. Two changes, both worth roughly a second each:
   *
   *   - Send the transcript the browser's own recogniser already produced while
   *     the user was speaking, instead of uploading the clip for Whisper to
   *     decode a second time.
   *   - Speak the answer with the local voice as soon as the text arrives,
   *     instead of waiting for the server to render an MP3.
   *
   * Costs a little accuracy on hard audio (accents, noise, unusual merchant
   * names), which is why it can be turned off. Audio upload remains the
   * automatic fallback whenever the recogniser gives us nothing.
   */
  fastMode: boolean;
  /**
   * `SpeechSynthesisVoice.voiceURI` of the chosen reply voice, or "" for the
   * browser default. Stored as the URI rather than an index because the voice
   * list order is not stable between sessions or machines.
   */
  voiceURI: string;
  /** Speaking rate. 1 is the engine default; the Web Speech range is 0.1-10. */
  speechRate: number;
  /** Speaking pitch. 1 is the engine default; the Web Speech range is 0-2. */
  speechPitch: number;
  /**
   * Vary rate and pitch slightly by what kind of answer it is, so a warning does
   * not land in the same tone as good news.
   *
   * This reacts to the answer's `intent`, which the backend already computes. It
   * is NOT emotion detection: nothing here infers how the user feels.
   */
  expressive: boolean;
  /** Stream the answer and start speaking the first sentence as it arrives. */
  streaming: boolean;
}

/** Web Speech API accepted ranges, used to clamp stored values. */
const RATE_RANGE = [0.5, 2] as const;
const PITCH_RANGE = [0, 2] as const;

function clamp(value: unknown, [min, max]: readonly [number, number], fallback: number) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

const STORAGE_KEY = "finzo.settings.v1";

export const TIMEOUT_OPTIONS = [10, 30, 60, 0] as const;

export const DEFAULT_SETTINGS: FinzoSettings = {
  enabled: false,
  muted: false,
  conversationTimeout: 30,
  autoSpeak: true,
  performanceMode: "standard",
  microphoneId: "",
  fastMode: true,
  voiceURI: "",
  // Slightly above default: 1.0 reads a little ponderous for short financial
  // answers, and anything past ~1.2 starts clipping digits.
  speechRate: 1.05,
  speechPitch: 1,
  expressive: true,
  streaming: true,
};

/** Coerce unknown stored JSON into valid settings; never throw on bad data. */
function coerce(raw: unknown): FinzoSettings {
  if (!raw || typeof raw !== "object") return { ...DEFAULT_SETTINGS };
  const r = raw as Partial<FinzoSettings>;
  const timeout = Number(r.conversationTimeout);
  return {
    enabled: r.enabled === true,
    muted: r.muted === true,
    conversationTimeout: (TIMEOUT_OPTIONS as readonly number[]).includes(timeout)
      ? timeout
      : DEFAULT_SETTINGS.conversationTimeout,
    autoSpeak: r.autoSpeak !== false,
    performanceMode: r.performanceMode === "low_cpu" ? "low_cpu" : "standard",
    microphoneId: typeof r.microphoneId === "string" ? r.microphoneId : "",
    // Defaults on, including for settings saved before this flag existed.
    fastMode: r.fastMode !== false,
    voiceURI: typeof r.voiceURI === "string" ? r.voiceURI : "",
    speechRate: clamp(r.speechRate, RATE_RANGE, DEFAULT_SETTINGS.speechRate),
    speechPitch: clamp(r.speechPitch, PITCH_RANGE, DEFAULT_SETTINGS.speechPitch),
    expressive: r.expressive !== false,
    streaming: r.streaming !== false,
  };
}

export function loadSettings(): FinzoSettings {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return { ...DEFAULT_SETTINGS };
    return coerce(JSON.parse(stored));
  } catch {
    // Corrupt or unavailable storage (private mode) must not break the app.
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(settings: FinzoSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    /* storage full or blocked: preferences simply will not persist */
  }
}

export function describeTimeout(seconds: number): string {
  if (seconds === 0) return "Never";
  if (seconds >= 60) return `${seconds / 60} min`;
  return `${seconds} sec`;
}
