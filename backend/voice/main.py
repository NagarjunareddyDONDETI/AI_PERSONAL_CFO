"""Finzo hands-free voice service.

Run from the ``backend`` directory:

    python -m voice.main                   listen on the microphone
    python -m voice.main --selftest        check every component, then exit
    python -m voice.main --list-devices    show microphones
    python -m voice.main --simulate q.wav  feed a WAV file instead of the mic
    python -m voice.main --stop            stop a running service

The web dashboard does not need to be open, and neither does the API server: the
service loads Finzo's pipeline in-process.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_BACKEND / ".env")

# Hugging Face noise on Windows without Developer Mode; harmless, but it floods
# the log of a background service.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from voice.handsfree import state as st  # noqa: E402

logger = logging.getLogger("voice.handsfree.main")


def _setup_logging(log_file: str | None, debug: bool) -> None:
    handlers: list[logging.Handler] = []
    # Under pythonw.exe (the background launcher) there is no console and
    # sys.stdout is None; the log file is the only sink then.
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    # Third-party chatter that would otherwise dominate the service log.
    for noisy in ("httpx", "httpcore", "faster_whisper", "chromadb", "urllib3", "comtypes"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_stop() -> int:
    doc = st.read_status()
    if not doc.get("running"):
        print("Finzo voice is not running.")
        return 0
    pid = doc.get("pid")
    st.stop_request_path().write_text(str(time.time()), encoding="utf-8")
    print(f"Asked Finzo voice (pid {pid}) to stop...")
    for _ in range(40):
        time.sleep(0.25)
        if not st.read_status().get("running"):
            print("Stopped.")
            return 0
    # Stuck in a model load or a long answer: end it.
    if pid and os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
        st.status_path().unlink(missing_ok=True)
        print("Stopped (forced).")
        return 0
    print("Could not confirm it stopped.")
    return 1


def cmd_list_devices() -> int:
    from voice.handsfree.audio import list_input_devices

    try:
        devices = list_input_devices()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not list audio devices: {exc}")
        return 2
    if not devices:
        print("No microphones found.")
        return 2
    for d in devices:
        star = "*" if d["default"] else " "
        print(f"{star} [{d['index']:>2}] {d['name']}  ({int(d['default_samplerate'] or 0)} Hz)")
    print("\n* = default. Set MIC_DEVICE to an index or part of a name to choose another.")
    return 0


def _build(args, cfg, voice_cfg):
    from voice.handsfree.assistant import HandsFreeAssistant, Transcriber
    from voice.handsfree.audio import FileSource, MicSource
    from voice.handsfree.bridge import CFOBridge
    from voice.handsfree.speaker import build_speaker
    from voice.handsfree.wake_detector import AlwaysAwake, WhisperWakeDetector

    bridge = CFOBridge(user_email=cfg.user_email)
    bridge.connect()

    wake = WhisperWakeDetector(
        phrase=cfg.wake_word,
        model=cfg.wake_model,
        device=voice_cfg.whisper_device,
        compute_type=voice_cfg.whisper_compute_type,
        probe_seconds=cfg.wake_probe_seconds,
    )
    if not cfg.wake_word_enabled:
        wake = AlwaysAwake(wake)
    transcriber = Transcriber(cfg, voice_cfg)
    speaker = build_speaker(
        ["none"] if args.no_tts else cfg.tts_chain,
        voice_hint=cfg.sapi_voice,
        rate=cfg.sapi_rate,
        playback=not args.no_playback,
        save_dir=args.save_speech,
    )

    logger.info("loading speech models (first run downloads them)...")
    wake.warm()
    transcriber.warm()

    if args.simulate:
        source = FileSource(args.simulate, sample_rate=cfg.sample_rate, frame_samples=cfg.frame_samples)
    else:
        source = MicSource(sample_rate=cfg.sample_rate, frame_samples=cfg.frame_samples, device=cfg.mic_device)

    status = st.StatusFile(
        static={
            "user_id": bridge.user_id,
            "wake_word": cfg.wake_word if cfg.wake_word_enabled else None,
            "stt": f"{','.join(cfg.stt_chain)} ({voice_cfg.whisper_model} on {transcriber.device})",
            "tts": speaker.engine_name,
            "simulated": bool(args.simulate),
        }
    )
    assistant = HandsFreeAssistant(
        cfg=cfg, source=source, wake=wake, transcriber=transcriber,
        speaker=speaker, bridge=bridge, status=status,
    )
    return assistant, status


def cmd_selftest(cfg, voice_cfg) -> int:
    """Check each component independently and report, without listening."""
    report: list[tuple[str, bool, str]] = []

    def check(name, fn):
        try:
            report.append((name, True, str(fn())))
        except Exception as exc:  # noqa: BLE001
            report.append((name, False, str(exc)[:200]))

    from voice.handsfree.audio import list_input_devices
    from voice.handsfree.bridge import CFOBridge
    from voice.handsfree.speaker import build_speaker
    from voice.stt.faster_whisper_local import cuda_status, load_model
    from voice.voicebox import get_client

    check("microphone", lambda: next(d["name"] for d in list_input_devices() if d["default"]))
    check(
        f"wake model {cfg.wake_model}",
        lambda: load_model(cfg.wake_model, voice_cfg.whisper_device, voice_cfg.whisper_compute_type).device,
    )
    check(
        f"stt model {voice_cfg.whisper_model}",
        lambda: load_model(voice_cfg.whisper_model, voice_cfg.whisper_device, voice_cfg.whisper_compute_type).device,
    )
    check("gpu", cuda_status)

    def _voicebox():
        h = get_client().health(use_cache=False)
        if not h.get("ok"):
            raise RuntimeError(h.get("error"))
        return f"{h.get('backend_type')} gpu={h.get('gpu_available')}"

    check("voicebox", _voicebox)

    def _tts():
        speaker = build_speaker(cfg.tts_chain, voice_hint=cfg.sapi_voice, rate=cfg.sapi_rate, playback=False)
        if not speaker.speak("Finzo voice check."):
            raise RuntimeError("no TTS engine produced audio")
        detail = f"{speaker.last_engine} ({speaker.last_audio_seconds:.1f}s)"
        # A fallback is a pass, but it must not look like the preferred engine
        # worked: that is how a missing Voicebox model went unnoticed.
        skipped = getattr(speaker, "last_failures", [])
        if skipped:
            detail += " -- fell back; " + "; ".join(f"{n}: {why}" for n, why in skipped)
        return detail

    check("tts", _tts)

    def _bridge():
        bridge = CFOBridge(user_email=cfg.user_email)
        bridge.connect()
        return f"user ok, statement={'yes' if bridge.has_data else 'NO - upload one'}"

    check("cfo pipeline", _bridge)

    width = max(len(n) for n, _, _ in report)
    for name, ok, detail in report:
        print(f"  {'OK  ' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    required = {"microphone", "cfo pipeline", "tts", f"stt model {voice_cfg.whisper_model}"}
    failed = [n for n, ok, _ in report if not ok and n in required]
    # Voicebox and CUDA are optional: the service falls back without them.
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m voice.main", description="Finzo hands-free voice")
    parser.add_argument("--simulate", metavar="WAV", help="use a WAV file instead of the microphone")
    parser.add_argument("--no-playback", action="store_true", help="render speech but do not play it")
    parser.add_argument("--no-tts", action="store_true", help="disable speech output entirely")
    parser.add_argument("--save-speech", metavar="DIR", help="also write each spoken answer as a WAV")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--log-file", default=str(st.state_dir() / "voice.log"))
    args = parser.parse_args(argv)

    from voice.config import load_config as load_voice_config
    from voice.handsfree.config import load_config

    cfg = load_config()
    voice_cfg = load_voice_config()
    _setup_logging(args.log_file, cfg.debug)

    if args.stop:
        return cmd_stop()
    if args.list_devices:
        return cmd_list_devices()
    if args.selftest:
        return cmd_selftest(cfg, voice_cfg)

    if not cfg.voice_enabled:
        print("VOICE_ENABLED=false in backend/.env; not starting.")
        return 0
    existing = st.read_status()
    if existing.get("running") and existing.get("pid") != os.getpid() and not args.simulate:
        print(f"Finzo voice is already running (pid {existing.get('pid')}).")
        return 1
    st.stop_request_path().unlink(missing_ok=True)

    try:
        assistant, status = _build(args, cfg, voice_cfg)
    except Exception as exc:  # noqa: BLE001
        logger.exception("startup failed")
        st.StatusFile().publish(st.VoiceState.ERROR, {"error": _friendly(exc)})
        print(f"Finzo voice could not start: {_friendly(exc)}")
        return 2

    def _on_signal(*_):
        assistant.request_stop()

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _on_signal)

    wake_hint = f'Say "{cfg.wake_word.title()}"' if cfg.wake_word_enabled else "Listening (no wake word)"
    logger.info("Finzo voice ready. %s.", wake_hint)
    try:
        assistant.run()
    finally:
        if not args.simulate:
            status.clear()

    if args.simulate:
        print(json.dumps({"turns": assistant.turns}, indent=2, ensure_ascii=False))
    return 0


def _friendly(exc: BaseException) -> str:
    """User-facing startup error. Details stay in the log."""
    text = str(exc)
    lowered = text.lower()
    if "portaudio" in lowered or "invalid device" in lowered or "no default input" in lowered:
        return "No usable microphone was found. Check it is plugged in and allowed in Windows privacy settings."
    if "finzo_voice_user_email" in lowered:
        return text
    if "faster-whisper" in lowered or "faster_whisper" in lowered:
        return "The speech model could not be loaded. Run the selftest for details."
    return text[:200]


if __name__ == "__main__":
    sys.exit(main())
