"""Standalone hands-free Finzo: microphone -> wake word -> STT -> CFO -> speech.

Runs as its own process (``python -m voice.main``) so it keeps working with the
web dashboard closed. Only ``state`` is imported by the API server; everything
else pulls in audio libraries and is loaded by the daemon alone.
"""
