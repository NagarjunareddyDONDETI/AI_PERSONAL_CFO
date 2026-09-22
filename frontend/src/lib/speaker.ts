/**
 * Local speech output: voice selection, prosody, and an ordered queue.
 *
 * Kept separate from `useFinzo` because it is the one part of the voice loop with
 * no React in it, and because streaming needs it to behave as a queue rather than
 * a single call. Sentences arrive from the network one at a time and must be
 * spoken back-to-back in order, with no gap and no overlap.
 *
 * `speechSynthesis` already queues utterances natively, which is what makes
 * streamed speech work without any audio buffering on our side: each sentence is
 * handed over as it arrives and the engine plays them consecutively.
 */
import { FinzoSettings } from "./finzoSettings";

export interface VoiceOption {
  voiceURI: string;
  name: string;
  lang: string;
  localService: boolean;
  default: boolean;
}

function synth(): SpeechSynthesis | null {
  return typeof window !== "undefined" && window.speechSynthesis
    ? window.speechSynthesis
    : null;
}

export function isSpeechOutputSupported(): boolean {
  return synth() !== null;
}

/**
 * Available voices, English first.
 *
 * Chrome populates the voice list asynchronously and returns an empty array on
 * the first call after load, so callers must also listen for `voiceschanged`
 * (see `subscribeVoices`) rather than trusting a single read.
 */
export function listVoices(): VoiceOption[] {
  const s = synth();
  if (!s) return [];
  return s
    .getVoices()
    .map((v) => ({
      voiceURI: v.voiceURI,
      name: v.name,
      lang: v.lang,
      localService: v.localService,
      default: v.default,
    }))
    .sort((a, b) => {
      const aEn = a.lang.toLowerCase().startsWith("en") ? 0 : 1;
      const bEn = b.lang.toLowerCase().startsWith("en") ? 0 : 1;
      return aEn - bEn || a.name.localeCompare(b.name);
    });
}

/** Watch for the voice list arriving or changing. Returns an unsubscribe fn. */
export function subscribeVoices(onChange: (voices: VoiceOption[]) => void): () => void {
  const s = synth();
  if (!s) return () => {};
  const emit = () => onChange(listVoices());
  emit();
  s.addEventListener?.("voiceschanged", emit);
  return () => s.removeEventListener?.("voiceschanged", emit);
}

/**
 * Prosody per answer kind.
 *
 * Driven by the `intent` the backend already computes for every answer. These are
 * multipliers on the user's chosen rate and offsets on their chosen pitch, so a
 * preference for a slow, low voice stays slow and low.
 *
 * To be explicit about what this is not: it reacts to the *topic* of the answer,
 * never to the user's emotional state. Nothing here detects emotion.
 */
const PROSODY: Record<string, { rate: number; pitch: number }> = {
  // Overspending, debt, anomalies: slower and lower reads as serious.
  warning: { rate: 0.96, pitch: -0.05 },
  anomaly: { rate: 0.96, pitch: -0.05 },
  debt: { rate: 0.96, pitch: -0.05 },
  // Good news: a touch quicker and brighter.
  savings: { rate: 1.04, pitch: 0.05 },
  goal: { rate: 1.04, pitch: 0.05 },
  // Figures should be easy to catch, so do not speed these up.
  spending: { rate: 1, pitch: 0 },
  forecast: { rate: 1, pitch: 0 },
};

export interface SpeakOptions {
  /** Answer intent, used for prosody when `expressive` is on. */
  intent?: string;
  /** Resolves when this utterance finishes (or is cancelled). */
  onEnd?: () => void;
}

/** Apply the user's voice, rate and pitch, plus any intent-based variation. */
function configure(
  utter: SpeechSynthesisUtterance,
  settings: FinzoSettings,
  intent?: string
): void {
  const s = synth();
  if (s && settings.voiceURI) {
    const match = s.getVoices().find((v) => v.voiceURI === settings.voiceURI);
    // A saved voice can disappear (different machine, uninstalled language
    // pack). Falling through to the engine default is better than silence.
    if (match) utter.voice = match;
  }

  const tone = settings.expressive && intent ? PROSODY[intent] : undefined;
  utter.rate = Math.min(2, Math.max(0.5, settings.speechRate * (tone?.rate ?? 1)));
  utter.pitch = Math.min(2, Math.max(0, settings.speechPitch + (tone?.pitch ?? 0)));
}

/**
 * Ordered speech queue.
 *
 * One instance per voice loop. `enqueue` can be called as each streamed sentence
 * lands; `cancel` stops everything immediately, which is what barge-in needs.
 */
export class Speaker {
  private settings: FinzoSettings;
  private pending = 0;
  private idleResolvers: Array<() => void> = [];
  private cancelled = false;

  constructor(settings: FinzoSettings) {
    this.settings = settings;
  }

  updateSettings(settings: FinzoSettings): void {
    this.settings = settings;
  }

  get speaking(): boolean {
    return this.pending > 0;
  }

  /** Queue one sentence. Returns false when speech output is unavailable. */
  enqueue(text: string, opts: SpeakOptions = {}): boolean {
    const s = synth();
    const trimmed = text.trim();
    if (!s || !trimmed) return false;

    this.cancelled = false;
    let utter: SpeechSynthesisUtterance;
    try {
      utter = new SpeechSynthesisUtterance(trimmed);
    } catch {
      return false;
    }
    configure(utter, this.settings, opts.intent);

    this.pending += 1;
    const settle = () => {
      this.pending = Math.max(0, this.pending - 1);
      opts.onEnd?.();
      if (this.pending === 0) this.drainIdle();
    };
    utter.onend = settle;
    utter.onerror = settle;

    try {
      s.speak(utter);
    } catch {
      settle();
      return false;
    }
    return true;
  }

  /**
   * Resolve once the queue empties.
   *
   * `timeoutMs` is a safety net, not a nicety: some engines never fire `onend`,
   * and without it the voice loop would wait forever and never resume listening.
   */
  waitUntilIdle(timeoutMs = 20000): Promise<void> {
    if (this.pending === 0) return Promise.resolve();
    return new Promise((resolve) => {
      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        resolve();
      };
      const timer = window.setTimeout(done, timeoutMs);
      this.idleResolvers.push(done);
    });
  }

  private drainIdle(): void {
    const waiting = this.idleResolvers;
    this.idleResolvers = [];
    waiting.forEach((fn) => fn());
  }

  /** Stop immediately and drop anything queued. Used for barge-in. */
  cancel(): void {
    this.cancelled = true;
    this.pending = 0;
    try {
      synth()?.cancel();
    } catch {
      /* ignore */
    }
    this.drainIdle();
  }

  get wasCancelled(): boolean {
    return this.cancelled;
  }
}
