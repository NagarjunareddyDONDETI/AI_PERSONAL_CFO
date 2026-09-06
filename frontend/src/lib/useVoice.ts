import { useCallback, useRef, useState } from "react";

// MediaRecorder-based mic capture with a live amplitude readout for the orb.
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

// Browser's built-in live speech recognition (interim results while speaking).
// Available in Chromium/Edge/Safari; gracefully skipped elsewhere.
function getSpeechRecognition(): any {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function useVoiceRecorder() {
  const [recording, setRecording] = useState(false);
  const [amplitude, setAmplitude] = useState(0);
  const [error, setError] = useState<string | null>(null);
  // Live text the browser hears in real time, shown during the animation.
  const [liveTranscript, setLiveTranscript] = useState("");

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const mimeRef = useRef<string>("audio/webm");
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number>(0);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const recognitionRef = useRef<any>(null);
  const finalizedRef = useRef<string>("");
  const startingRef = useRef(false);

  // Returns null on success, or an error message string on failure.
  const start = useCallback(async (): Promise<string | null> => {
    setError(null);
    const fail = (msg: string) => {
      startingRef.current = false;
      setError(msg);
      return msg;
    };
    // getUserMedia is awaited before `recording` flips true, so a second tap in
    // that window would open a second recorder and leak the first mic stream.
    if (startingRef.current || recorderRef.current) return null;
    startingRef.current = true;
    // getUserMedia only exists in a secure context (https:// or localhost).
    if (!navigator.mediaDevices?.getUserMedia) {
      return fail(
        window.isSecureContext === false
          ? "Microphone needs a secure page. Open the app via http://localhost:5173 (not an IP address) or use HTTPS."
          : "This browser doesn't expose microphone access (navigator.mediaDevices is unavailable)."
      );
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;
      chunksRef.current = [];

      const mimeType = pickMimeType();
      mimeRef.current = mimeType || "audio/webm";
      const rec = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      recorderRef.current = rec;
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      // timeslice flushes data periodically so we never lose the tail.
      rec.start(250);

      // amplitude analyser for the orb
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      analyserRef.current = analyser;
      const buf = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        setAmplitude(Math.min(1, Math.sqrt(sum / buf.length) * 3));
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();

      // live interim transcription (best-effort, independent of Whisper)
      setLiveTranscript("");
      finalizedRef.current = "";
      const SR = getSpeechRecognition();
      if (SR) {
        try {
          const recog = new SR();
          recog.lang = "en-US";
          recog.continuous = true;
          recog.interimResults = true;
          recog.onresult = (event: any) => {
            let interim = "";
            for (let i = event.resultIndex; i < event.results.length; i++) {
              const chunk = event.results[i][0].transcript;
              if (event.results[i].isFinal) {
                finalizedRef.current = (finalizedRef.current + " " + chunk).trim();
              } else {
                interim += chunk;
              }
            }
            setLiveTranscript((finalizedRef.current + " " + interim).trim());
          };
          recog.onerror = () => {};
          recognitionRef.current = recog;
          recog.start();
        } catch {
          recognitionRef.current = null;
        }
      }

      startingRef.current = false;
      setRecording(true);
      return null;
    } catch (e) {
      // Map the common DOMException names to actionable messages.
      const name = e instanceof DOMException ? e.name : "";
      switch (name) {
        case "NotAllowedError":
        case "SecurityError":
          return fail(
            "Microphone permission was blocked. Click the padlock/🎤 icon in the address bar, allow the mic, then reload and try again."
          );
        case "NotFoundError":
        case "OverconstrainedError":
          return fail("No microphone was found. Plug in or enable a mic, then try again.");
        case "NotReadableError":
          return fail(
            "Your microphone is being used by another app. Close it (Zoom/Teams/etc.) and try again."
          );
        default:
          return fail(
            (e instanceof Error && e.message) ||
              "Microphone access failed. Check browser permissions."
          );
      }
    }
  }, []);

  // Release the mic, analyser and recogniser. Safe to call more than once.
  const teardown = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    analyserRef.current = null;
    try {
      recognitionRef.current?.stop();
    } catch {
      /* ignore */
    }
    recognitionRef.current = null;
    recorderRef.current = null;
    setAmplitude(0);
    setRecording(false);
  }, []);

  const stop = useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const rec = recorderRef.current;
      const collected = () =>
        chunksRef.current.length
          ? new Blob(chunksRef.current, { type: mimeRef.current })
          : null;

      // This promise MUST always settle. It previously resolved only from
      // rec.onstop, so if stop() threw (recorder already inactive) or onstop
      // never fired, the caller awaited forever and the UI hung on "Thinking…".
      let settled = false;
      const finish = (blob: Blob | null) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        teardown();
        resolve(blob);
      };

      const timer = setTimeout(() => finish(collected()), 2500);

      if (!rec || rec.state === "inactive") {
        finish(collected());
        return;
      }

      rec.onstop = () => finish(collected());
      rec.onerror = () => finish(collected());
      try {
        // Flush the current timeslice so the tail of speech is not lost.
        rec.requestData?.();
        rec.stop();
      } catch {
        finish(collected());
      }
    });
  }, [teardown]);

  return { recording, amplitude, error, start, stop, liveTranscript };
}
