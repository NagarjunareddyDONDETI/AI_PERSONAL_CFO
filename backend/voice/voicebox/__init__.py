"""Voicebox integration, isolated behind one client.

Import from here only inside ``voice/``. Application code uses the STT/TTS
registries, which treat Voicebox as one provider among several.
"""
from .client import (
    VoiceboxBadResponse,
    VoiceboxClient,
    VoiceboxError,
    VoiceboxNotReady,
    VoiceboxUnavailable,
    get_client,
)
from .config import VoiceboxConfig, load_config

__all__ = [
    "VoiceboxBadResponse",
    "VoiceboxClient",
    "VoiceboxConfig",
    "VoiceboxError",
    "VoiceboxNotReady",
    "VoiceboxUnavailable",
    "get_client",
    "load_config",
]
