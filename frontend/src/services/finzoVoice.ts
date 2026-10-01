/**
 * Push-to-talk voice I/O for Finzo: microphone capture and answer playback.
 *
 * Browser-side plumbing only. Transcription, the financial answer and speech
 * synthesis all happen on the backend (Voicebox first, local fallbacks after),
 * so this module never sees or computes a financial figure.
 */
import { FinzoVoiceChatResult, finzoVoiceChat } from "../api";

export type MicErrorKind = "denied" | "no-device" | "busy" | "insecure" | "unsupported" | "unknown";

export class MicError extends Error {
  constructor(public kind: MicErrorKind, message: string) {
    super(message);
    this.name = "MicError";
  }
}

const MIC_MESSAGES: Record<MicErrorKind, string> = {
  denied: "Microphone access is blocked. Allow it from the address bar, then try again.",
  "no-device": "No microphone was found.",
  busy: "Your microphone is being used by another app.",
  insecure: "The microphone needs a secure page. Open the app on http://localhost:5173 or over HTTPS.",
  unsupported: "This browser can't record audio. You can type your question instead.",
  unknown: "The microphone couldn't be started.",
};

/** Map a getUserMedia failure to something a person can act on. */
export function toMicError(e: unknown): MicError {
  if (e instanceof MicError) return e;
  const name = e instanceof DOMException ? e.name : "";
  const kind: MicErrorKind =
    name === "NotAllowedError" || name === "SecurityError"
      ? "denied"
      : name === "NotFoundError" || name === "OverconstrainedError"
        ? "no-device"
        : name === "NotReadableError" || name === "AbortError"
          ? "busy"
          : "unknown";
  return new MicError(kind, MIC_MESSAGES[kind]);
}

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";
  for (const t of ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"]) {
    if (MediaRecorder.isTypeSupported(t)) return t;
  }
  return "";
}

/** Voicebox rejects clips this short, and they are almost always a mis-tap. */
const MIN_RECORDING_MS = 400;
/** Push-to-talk safety net: a stuck button must not record forever. */
const MAX_RECORDING_MS = 30_000;

export interface Recording {
  blob: Blob;
  durationMs: number;
}

/**
 * One push-to-talk capture. `start()` on press, `stop()` on release.
 *
 * Exposes an AnalyserNode so the visualizer can draw live input levels.
 */
export class PushToTalkRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private startedAt = 0;
  private audioCtx: AudioContext | null = null;
  private maxTimer: number | null = null;
  analyser: AnalyserNode | null = null;
  onAutoStop: (() => void) | null = null;

  static supported(): boolean {
    return (
      typeof navigator !== "undefined" &&
      !!navigator.mediaDevices?.getUserMedia &&
      typeof MediaRecorder !== "undefined"
    );
  }

  async start(): Promise<void> {
    if (window.isSecureContext === false) throw new MicError("insecure", MIC_MESSAGES.insecure);
    if (!PushToTalkRecorder.supported()) throw new MicError("unsupported", MIC_MESSAGES.unsupported);
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      throw toMicError(e);
    }

    try {
      const Ctor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.audioCtx = new Ctor();
      const source = this.audioCtx.createMediaStreamSource(this.stream);
      this.analyser = this.audioCtx.createAnalyser();
      this.analyser.fftSize = 256;
      source.connect(this.analyser);
    } catch {
      this.analyser = null; // visualizer falls back to a static animation
    }

    const mime = pickMimeType();
    this.chunks = [];
    this.recorder = mime ? new MediaRecorder(this.stream, { mimeType: mime }) : new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.chunks.push(e.data);
    };
    this.recorder.start(250);
    this.startedAt = performance.now();
    this.maxTimer = window.setTimeout(() => this.onAutoStop?.(), MAX_RECORDING_MS);
  }

  /** Stop and return the clip, or null when it was too short to be a question. */
  stop(): Promise<Recording | null> {
    return new Promise((resolve) => {
      const rec = this.recorder;
      const durationMs = performance.now() - this.startedAt;
      const finish = () => {
        const type = rec?.mimeType || "audio/webm";
        const blob = new Blob(this.chunks, { type });
        this.release();
        resolve(durationMs < MIN_RECORDING_MS || blob.size < 1024 ? null : { blob, durationMs });
      };
      if (!rec || rec.state === "inactive") return finish();
      rec.onstop = finish;
      try {
        rec.requestData?.();
        rec.stop();
      } catch {
        finish();
      }
    });
  }

  /** Always release the microphone; a lingering stream keeps the OS mic light on. */
  release(): void {
    if (this.maxTimer !== null) window.clearTimeout(this.maxTimer);
    this.maxTimer = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.recorder = null;
    this.analyser = null;
    this.audioCtx?.close().catch(() => {});
    this.audioCtx = null;
  }
}

/**
 * Plays answers one at a time. Starting a new answer always stops the old one,
 * so two responses can never overlap.
 */
export class AnswerPlayer {
  private el: HTMLAudioElement | null = null;
  private resolveCurrent: (() => void) | null = null;
  analyser: AnalyserNode | null = null;
  private ctx: AudioContext | null = null;

  /** Resolves when playback ends, fails, or is stopped. Rejects only if autoplay is blocked. */
  play(audioB64: string, mime: string | null | undefined): Promise<void> {
    this.stop();
    if (!this.el) {
      this.el = new Audio();
      this.el.crossOrigin = "anonymous";
      try {
        const Ctor = window.AudioContext;
        this.ctx = new Ctor();
        const src = this.ctx.createMediaElementSource(this.el);
        this.analyser = this.ctx.createAnalyser();
        this.analyser.fftSize = 256;
        src.connect(this.analyser);
        this.analyser.connect(this.ctx.destination);
      } catch {
        this.analyser = null;
      }
    }
    const el = this.el;
    el.src = `data:${mime || "audio/mpeg"};base64,${audioB64}`;
    return new Promise((resolve, reject) => {
      const done = () => {
        this.resolveCurrent = null;
        resolve();
      };
      this.resolveCurrent = done;
      el.onended = done;
      el.onerror = done;
      this.ctx?.resume().catch(() => {});
      el.play().catch((err) => {
        this.resolveCurrent = null;
        reject(err);
      });
    });
  }

  stop(): void {
    if (this.el) {
      this.el.pause();
      this.el.currentTime = 0;
    }
    this.resolveCurrent?.();
    this.resolveCurrent = null;
  }

  dispose(): void {
    this.stop();
    this.ctx?.close().catch(() => {});
    this.ctx = null;
    this.el = null;
  }
}

/** Ask a question by voice (or typed fallback) and get the verified answer. */
export function askFinzo(
  input: { audio?: Blob | null; transcript?: string },
  signal?: AbortSignal
): Promise<FinzoVoiceChatResult> {
  return finzoVoiceChat(input, { speak: true, signal });
}
