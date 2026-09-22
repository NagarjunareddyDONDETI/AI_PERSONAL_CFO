/**
 * Voice activity detection over an existing MediaStream.
 *
 * Purpose: stop the query recording as soon as the user stops talking, instead of
 * waiting out a fixed recording window. A fixed 10-second clip adds up to ten
 * seconds of dead air before the assistant even starts thinking, which is the
 * single biggest thing that makes a voice assistant feel slow.
 *
 * Deliberately RMS-over-AnalyserNode rather than a neural VAD: it costs one small
 * FFT read per animation frame, needs no model download, and the decision here is
 * only "is anyone talking", which loudness answers well enough.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export interface VadOptions {
  /** Analyser RMS (0-1) above which audio counts as speech. */
  threshold?: number;
  /** Trailing silence before speech is considered finished. */
  silenceMs?: number;
  /** Ignore blips shorter than this, so a cough is not a query. */
  minSpeechMs?: number;
  /** Hard stop, so a stuck-open mic cannot record forever. */
  maxUtteranceMs?: number;
  /** Fires once trailing silence has elapsed after real speech. */
  onSpeechEnd?: () => void;
  onSpeechStart?: () => void;
  /** Fires if maxUtteranceMs is hit. */
  onMaxDuration?: () => void;
  /** Low-CPU mode: sample less often. */
  lowPower?: boolean;
}

export const VAD_DEFAULTS = {
  threshold: 0.045,
  // Trailing silence is dead air on every single turn, so it is the cheapest
  // latency to buy back. 550ms is long enough to ride out the pause between
  // clauses ("last month... uh... on groceries") without cutting people off, and
  // noticeably snappier than the ~900ms that reads as a lag.
  silenceMs: 550,
  minSpeechMs: 220,
  maxUtteranceMs: 15000,
} as const;

export function useVad(stream: MediaStream | null, options: VadOptions = {}) {
  const {
    threshold = VAD_DEFAULTS.threshold,
    silenceMs = VAD_DEFAULTS.silenceMs,
    minSpeechMs = VAD_DEFAULTS.minSpeechMs,
    maxUtteranceMs = VAD_DEFAULTS.maxUtteranceMs,
    onSpeechEnd,
    onSpeechStart,
    onMaxDuration,
    lowPower = false,
  } = options;

  const [amplitude, setAmplitude] = useState(0);
  const [speaking, setSpeaking] = useState(false);

  const ctxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number>(0);
  const timerRef = useRef<number | null>(null);
  const speechStartedAtRef = useRef<number>(0);
  const lastLoudAtRef = useRef<number>(0);
  const firedRef = useRef(false);
  const startedAtRef = useRef<number>(0);

  // Refs so changing a callback does not rebuild the audio graph mid-utterance.
  const endRef = useRef(onSpeechEnd);
  const startRef = useRef(onSpeechStart);
  const maxRef = useRef(onMaxDuration);
  useEffect(() => {
    endRef.current = onSpeechEnd;
    startRef.current = onSpeechStart;
    maxRef.current = onMaxDuration;
  }, [onSpeechEnd, onSpeechStart, onMaxDuration]);

  const reset = useCallback(() => {
    firedRef.current = false;
    speechStartedAtRef.current = 0;
    lastLoudAtRef.current = 0;
    startedAtRef.current = performance.now();
    setSpeaking(false);
  }, []);

  useEffect(() => {
    if (!stream) {
      setAmplitude(0);
      setSpeaking(false);
      return;
    }

    let cancelled = false;
    let ctx: AudioContext | null = null;
    let analyser: AnalyserNode | null = null;

    try {
      const Ctor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      ctx = new Ctor();
      ctxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      analyser = ctx.createAnalyser();
      // 512 gives a stable RMS without the cost of a large transform.
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.6;
      source.connect(analyser);
    } catch {
      // No AudioContext: the caller falls back to a fixed recording window.
      return;
    }

    const buffer = new Uint8Array(analyser.frequencyBinCount);
    reset();

    // In low-power mode sample on a timer instead of every frame: ~15/s still
    // resolves the silence window to within a frame and costs a fraction of the
    // CPU.
    const sampleIntervalMs = lowPower ? 66 : 0;
    let lastSampleAt = 0;

    const tick = (now: number) => {
      if (cancelled || !analyser) return;

      if (sampleIntervalMs && now - lastSampleAt < sampleIntervalMs) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }
      lastSampleAt = now;

      analyser.getByteTimeDomainData(buffer);
      let sum = 0;
      for (let i = 0; i < buffer.length; i++) {
        const v = (buffer[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / buffer.length);
      setAmplitude(Math.min(1, rms * 3));

      const loud = rms >= threshold;
      if (loud) {
        lastLoudAtRef.current = now;
        if (!speechStartedAtRef.current) {
          speechStartedAtRef.current = now;
          setSpeaking(true);
          startRef.current?.();
        }
      } else if (speechStartedAtRef.current && !firedRef.current) {
        const spoke = lastLoudAtRef.current - speechStartedAtRef.current;
        const silent = now - lastLoudAtRef.current;
        // Both conditions matter: enough speech to be a real utterance, and
        // enough silence to be confident the user is finished.
        if (silent >= silenceMs && spoke >= minSpeechMs) {
          firedRef.current = true;
          setSpeaking(false);
          endRef.current?.();
          return;
        }
        // Sub-threshold blip (cough, door). Discard and keep waiting.
        if (silent >= silenceMs && spoke < minSpeechMs) {
          speechStartedAtRef.current = 0;
          setSpeaking(false);
        }
      }

      if (!firedRef.current && now - startedAtRef.current >= maxUtteranceMs) {
        firedRef.current = true;
        setSpeaking(false);
        maxRef.current?.();
        return;
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafRef.current);
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      timerRef.current = null;
      ctx?.close().catch(() => {});
      ctxRef.current = null;
      setAmplitude(0);
      setSpeaking(false);
    };
  }, [stream, threshold, silenceMs, minSpeechMs, maxUtteranceMs, lowPower, reset]);

  return { amplitude, speaking, reset };
}
