"""Optional Gemini music-intelligence layer.

Gemini does not transcribe notes. It validates and patches the existing
Audio → MIDI → Score pipeline when ENABLE_GEMINI_MUSIC_ANALYSIS is on.
"""

from intelligence.config import GeminiConfig, gemini_config
from intelligence.layer import maybe_enhance

__all__ = ["GeminiConfig", "gemini_config", "maybe_enhance"]
