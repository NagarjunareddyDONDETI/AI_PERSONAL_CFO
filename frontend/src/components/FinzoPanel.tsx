/**
 * Finzo hands-free panel.
 *
 * Sits alongside the existing chat panel rather than replacing it: typing must
 * always remain available, and voice is an additional way in, not a substitute.
 *
 * Privacy is deliberately loud. Whenever the microphone is live the panel says so
 * in words, and a mute control is visible at all times -- an always-on microphone
 * that is not obviously on would be indefensible in an app holding bank
 * statements.
 */
import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  DEFAULT_SETTINGS,
  FinzoSettings,
  TIMEOUT_OPTIONS,
  describeTimeout,
  loadSettings,
  saveSettings,
} from "../lib/finzoSettings";
import { STATUS_LABEL, isMicActive } from "../lib/voiceMachine";
import { useFinzo } from "../lib/useFinzo";
import { VoiceOption, subscribeVoices } from "../lib/speaker";
import FinzoOrb from "./FinzoOrb";
import GlassCard from "./GlassCard";

interface Props {
  delay?: number;
}

export default function FinzoPanel({ delay = 0 }: Props) {
  const [settings, setSettings] = useState<FinzoSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [hydrated, setHydrated] = useState(false);

  // Load persisted preferences after mount, so the first paint never assumes the
  // microphone should be on.
  useEffect(() => {
    setSettings(loadSettings());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated) saveSettings(settings);
  }, [settings, hydrated]);

  const finzo = useFinzo({ settings });

  const update = <K extends keyof FinzoSettings>(key: K, value: FinzoSettings[K]) =>
    setSettings((s) => ({ ...s, [key]: value }));

  // Device labels are only exposed after permission has been granted once.
  useEffect(() => {
    if (!showSettings || !navigator.mediaDevices?.enumerateDevices) return;
    navigator.mediaDevices
      .enumerateDevices()
      .then((all) => setDevices(all.filter((d) => d.kind === "audioinput")))
      .catch(() => setDevices([]));
  }, [showSettings]);

  // Chrome returns an empty voice list on the first read after load and fills it
  // in asynchronously, so subscribe rather than reading once.
  useEffect(() => subscribeVoices(setVoices), []);

  const micLive = isMicActive(finzo.state) || finzo.micActive;

  const statusLine = useMemo(() => {
    if (finzo.unsupported) return "Hands-free voice is not supported in this browser";
    if (!settings.enabled) return "Voice assistant off";
    if (settings.muted) return "Microphone muted";
    return STATUS_LABEL[finzo.state];
  }, [finzo.state, finzo.unsupported, settings.enabled, settings.muted]);

  const lastUser = [...finzo.turns].reverse().find((t) => t.role === "user");
  const lastFinzo = [...finzo.turns].reverse().find((t) => t.role === "finzo");

  return (
    <GlassCard
      title="Finzo"
      subtitle="Hands-free voice assistant"
      delay={delay}
    >
      {/* ---- privacy banner: always visible, never subtle ---- */}
      <div
        role="status"
        className={`mb-4 flex items-center justify-between gap-3 rounded-xl border px-3 py-2 ${
          micLive
            ? "border-teal-accent/40 bg-teal-accent/10"
            : "border-white/10 bg-white/5"
        }`}
      >
        <span className="flex items-center gap-2 text-[12px]">
          <span
            aria-hidden="true"
            className={`h-2 w-2 rounded-full ${
              micLive ? "animate-pulseGlow bg-teal-accent" : "bg-slate-500"
            }`}
          />
          <span className={micLive ? "text-teal-accent" : "text-slate-400"}>
            {micLive ? "Microphone is live" : "Microphone is off"}
          </span>
        </span>

        <div className="flex items-center gap-2">
          {settings.enabled && (
            <button
              onClick={() => update("muted", !settings.muted)}
              className="rounded-lg border border-white/10 px-2.5 py-1 text-[11px] text-slate-300 transition-colors hover:bg-white/10"
              aria-pressed={settings.muted}
            >
              {settings.muted ? "Unmute" : "Mute mic"}
            </button>
          )}
          <button
            onClick={() => setShowSettings((v) => !v)}
            aria-expanded={showSettings}
            className="rounded-lg border border-white/10 px-2.5 py-1 text-[11px] text-slate-300 transition-colors hover:bg-white/10"
          >
            Settings
          </button>
        </div>
      </div>

      {/* ---- settings ---- */}
      <AnimatePresence>
        {showSettings && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22 }}
            className="mb-4 overflow-hidden"
          >
            <div className="space-y-3 rounded-xl border border-white/10 bg-black/20 p-3">
              <label className="flex items-center justify-between text-[12px] text-slate-300">
                Voice assistant
                <input
                  type="checkbox"
                  checked={settings.enabled}
                  disabled={finzo.unsupported}
                  onChange={(e) => update("enabled", e.target.checked)}
                  className="h-4 w-4 accent-teal-accent"
                />
              </label>

              <label className="flex items-center justify-between text-[12px] text-slate-300">
                Speak answers aloud
                <input
                  type="checkbox"
                  checked={settings.autoSpeak}
                  onChange={(e) => update("autoSpeak", e.target.checked)}
                  className="h-4 w-4 accent-teal-accent"
                />
              </label>

              <div>
                <label className="flex items-center justify-between text-[12px] text-slate-300">
                  Fast replies
                  <input
                    type="checkbox"
                    checked={settings.fastMode}
                    onChange={(e) => update("fastMode", e.target.checked)}
                    className="h-4 w-4 accent-teal-accent"
                  />
                </label>
                <p className="mt-1 text-[11px] leading-snug text-slate-500">
                  Uses this device for speech recognition and the reply voice.
                  Around two seconds faster per answer. Turn off for better
                  accuracy on noisy audio or strong accents.
                </p>
              </div>

              <div>
                <label className="flex items-center justify-between text-[12px] text-slate-300">
                  Start speaking sooner
                  <input
                    type="checkbox"
                    checked={settings.streaming}
                    onChange={(e) => update("streaming", e.target.checked)}
                    className="h-4 w-4 accent-teal-accent"
                  />
                </label>
                <p className="mt-1 text-[11px] leading-snug text-slate-500">
                  Reads the first sentence while the rest of the answer is still
                  being written, instead of waiting for all of it.
                </p>
              </div>

              {settings.autoSpeak && (
                <div className="space-y-2.5 border-t border-white/10 pt-3">
                  {voices.length > 0 ? (
                    <div className="text-[12px] text-slate-300">
                      <label htmlFor="finzo-voice" className="mb-1.5 block">
                        Reply voice
                      </label>
                      <select
                        id="finzo-voice"
                        value={settings.voiceURI}
                        onChange={(e) => update("voiceURI", e.target.value)}
                        className="w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 text-[12px] text-slate-200 outline-none focus:border-teal-accent/50"
                      >
                        <option value="">Browser default</option>
                        {voices.map((v) => (
                          <option key={v.voiceURI} value={v.voiceURI}>
                            {v.name} ({v.lang})
                          </option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-500">
                      No speech voices reported by this browser yet.
                    </p>
                  )}

                  <div className="text-[12px] text-slate-300">
                    <label htmlFor="finzo-rate" className="mb-1 flex justify-between">
                      <span>Speed</span>
                      <span className="font-mono text-[11px] text-slate-500">
                        {settings.speechRate.toFixed(2)}x
                      </span>
                    </label>
                    <input
                      id="finzo-rate"
                      type="range"
                      min={0.5}
                      max={2}
                      step={0.05}
                      value={settings.speechRate}
                      onChange={(e) => update("speechRate", Number(e.target.value))}
                      className="w-full accent-teal-accent"
                    />
                  </div>

                  <div className="text-[12px] text-slate-300">
                    <label htmlFor="finzo-pitch" className="mb-1 flex justify-between">
                      <span>Pitch</span>
                      <span className="font-mono text-[11px] text-slate-500">
                        {settings.speechPitch.toFixed(2)}
                      </span>
                    </label>
                    <input
                      id="finzo-pitch"
                      type="range"
                      min={0}
                      max={2}
                      step={0.05}
                      value={settings.speechPitch}
                      onChange={(e) => update("speechPitch", Number(e.target.value))}
                      className="w-full accent-teal-accent"
                    />
                  </div>

                  <div>
                    <label className="flex items-center justify-between text-[12px] text-slate-300">
                      Vary tone by topic
                      <input
                        type="checkbox"
                        checked={settings.expressive}
                        onChange={(e) => update("expressive", e.target.checked)}
                        className="h-4 w-4 accent-teal-accent"
                      />
                    </label>
                    <p className="mt-1 text-[11px] leading-snug text-slate-500">
                      Reads overspending warnings a little slower and lower, good
                      news a little brighter. Based on the topic of the answer, not
                      on how you sound.
                    </p>
                  </div>
                </div>
              )}

              <div className="text-[12px] text-slate-300">
                <p className="mb-1.5">Wake word</p>
                <p className="rounded-lg bg-white/5 px-2.5 py-1.5 font-mono text-[12px] text-teal-accent">
                  "Finzo" · "Hey Finzo" · "Okay Finzo"
                </p>
              </div>

              <div className="text-[12px] text-slate-300">
                <p className="mb-1.5">Conversation timeout</p>
                <div className="flex gap-1.5">
                  {TIMEOUT_OPTIONS.map((opt) => (
                    <button
                      key={opt}
                      onClick={() => update("conversationTimeout", opt)}
                      aria-pressed={settings.conversationTimeout === opt}
                      className={`rounded-lg px-2.5 py-1 text-[11px] transition-colors ${
                        settings.conversationTimeout === opt
                          ? "bg-teal-accent text-navy-900"
                          : "bg-white/5 text-slate-300 hover:bg-white/10"
                      }`}
                    >
                      {describeTimeout(opt)}
                    </button>
                  ))}
                </div>
              </div>

              <div className="text-[12px] text-slate-300">
                <p className="mb-1.5">Performance</p>
                <div className="flex gap-1.5">
                  {(["standard", "low_cpu"] as const).map((mode) => (
                    <button
                      key={mode}
                      onClick={() => update("performanceMode", mode)}
                      aria-pressed={settings.performanceMode === mode}
                      className={`rounded-lg px-2.5 py-1 text-[11px] transition-colors ${
                        settings.performanceMode === mode
                          ? "bg-violet-accent text-navy-900"
                          : "bg-white/5 text-slate-300 hover:bg-white/10"
                      }`}
                    >
                      {mode === "standard" ? "Standard" : "Low CPU"}
                    </button>
                  ))}
                </div>
              </div>

              {devices.length > 0 && (
                <div className="text-[12px] text-slate-300">
                  <label htmlFor="finzo-mic" className="mb-1.5 block">
                    Microphone
                  </label>
                  <select
                    id="finzo-mic"
                    value={settings.microphoneId}
                    onChange={(e) => update("microphoneId", e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 text-[12px] text-slate-200 outline-none focus:border-teal-accent/50"
                  >
                    <option value="">System default</option>
                    {devices.map((d) => (
                      <option key={d.deviceId} value={d.deviceId}>
                        {d.label || "Microphone"}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ---- orb + status ---- */}
      <div className="flex flex-col items-center py-2">
        <FinzoOrb state={finzo.state} amplitude={finzo.amplitude} />

        <p
          aria-live="polite"
          className="mt-3 min-h-[1.25rem] text-center text-[13px] font-medium text-slate-200"
        >
          {statusLine}
        </p>

        {finzo.conversationActive && (
          <p className="mt-1 text-[11px] text-slate-500">
            Follow-ups need no wake word · say "stop" to interrupt
          </p>
        )}

        {!settings.enabled && !finzo.unsupported && (
          <button
            onClick={async () => {
              // Ask for the microphone inside the click. Letting the speech
              // recogniser raise the prompt from an effect instead is the
              // flakiest path through Chrome's permission model.
              await finzo.primePermission();
              update("enabled", true);
            }}
            className="mt-4 rounded-xl bg-gradient-to-r from-teal-accent to-violet-accent px-5 py-2 text-[13px] font-bold text-navy-900 transition-transform hover:scale-[1.03]"
          >
            Enable hands-free voice
          </button>
        )}

        {settings.enabled && !settings.muted && !finzo.unsupported && (
          <div className="mt-4 flex gap-2">
            <button
              onClick={finzo.startManualQuery}
              className="rounded-xl border border-white/15 px-4 py-2 text-[12px] text-slate-200 transition-colors hover:bg-white/10"
            >
              Ask without wake word
            </button>
            {finzo.state === "SPEAKING" && (
              <button
                onClick={finzo.interrupt}
                className="rounded-xl bg-rose-500/20 px-4 py-2 text-[12px] font-semibold text-rose-200"
              >
                Stop
              </button>
            )}
          </div>
        )}

        {finzo.state === "ERROR" && (
          <button
            onClick={finzo.recover}
            className="mt-3 rounded-lg border border-white/15 px-3 py-1.5 text-[11px] text-slate-300 hover:bg-white/10"
          >
            Try again
          </button>
        )}
      </div>

      {/* ---- errors ---- */}
      {finzo.error && (
        <p role="alert" className="mt-2 rounded-lg bg-rose-500/10 px-3 py-2 text-[12px] text-rose-200">
          {finzo.error}
        </p>
      )}

      {finzo.unsupported && (
        <p className="mt-2 rounded-lg bg-amber-500/10 px-3 py-2 text-[12px] text-amber-200">
          Hands-free voice needs Chrome, Edge or Safari. The Advisor chat below
          works normally either way.
        </p>
      )}

      {/* ---- last exchange ---- */}
      {(lastUser || lastFinzo) && (
        <div className="mt-4 space-y-2 border-t border-white/5 pt-3">
          {lastUser && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500">You said</p>
              <p className="text-[13px] text-slate-200">{lastUser.text}</p>
            </div>
          )}
          {lastFinzo && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-teal-accent">Finzo</p>
              <p className="text-[13px] leading-relaxed text-slate-300">{lastFinzo.text}</p>
            </div>
          )}
        </div>
      )}

      {/* ---- diagnostics ----
          Without this, a non-responsive wake word is indistinguishable from a
          disabled microphone, a browser that lacks the API, and a recogniser
          that is running but mishearing. "Heard" updating as you speak is the
          single most useful signal: if it moves, capture works and only the
          matching is at fault. */}
      {settings.enabled && (
        <details className="mt-4 rounded-xl border border-white/10 bg-black/20">
          <summary className="cursor-pointer px-3 py-2 text-[11px] text-slate-400">
            Diagnostics
          </summary>
          <div className="space-y-1.5 px-3 pb-3 text-[11px]">
            <p className="flex justify-between gap-3">
              <span className="text-slate-500">Browser support</span>
              <span className={finzo.unsupported ? "text-rose-300" : "text-teal-accent"}>
                {finzo.unsupported ? "unsupported" : "ok"}
              </span>
            </p>
            <p className="flex justify-between gap-3">
              <span className="text-slate-500">Wake listener</span>
              <span className={finzo.wakeListening ? "text-teal-accent" : "text-amber-300"}>
                {finzo.wakeListening ? "running" : "not running"}
              </span>
            </p>
            <p className="flex justify-between gap-3">
              <span className="text-slate-500">State</span>
              <span className="font-mono text-slate-300">{finzo.state}</span>
            </p>
            <p className="flex justify-between gap-3">
              <span className="text-slate-500">Secure context</span>
              <span className={window.isSecureContext ? "text-teal-accent" : "text-rose-300"}>
                {window.isSecureContext ? "yes" : "no — mic blocked"}
              </span>
            </p>
            <div>
              <p className="mb-1 text-slate-500">Heard (say anything)</p>
              <p className="min-h-[1.5rem] rounded-lg bg-white/5 px-2 py-1 font-mono text-[11px] text-slate-300">
                {finzo.lastHeard || "—"}
              </p>
            </div>
            <p className="pt-1 text-slate-500">
              If "Heard" stays empty while you talk, the microphone or the browser
              recogniser is the problem, not the wake word.
            </p>
          </div>
        </details>
      )}

      <p className="mt-4 text-[11px] leading-relaxed text-slate-500">
        While idle, speech is matched on your device and nothing is uploaded. Only
        the clip containing your question is sent for transcription, and no audio
        is stored.
      </p>
    </GlassCard>
  );
}
