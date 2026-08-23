"""Audio Intelligence Layer."""

from audio_engine.normalizer import AudioNormalizer, NormalizedAudio
from audio_engine.instrument_classifier import InstrumentClassifier
from audio_engine.segmenter import AudioSegmenter
from audio_engine.onset_detector import OnsetDetector
from audio_engine.pitch_extractor import PitchExtractor
from audio_engine.polyphonic_decoder import PolyphonicDecoder
from audio_engine.beat_tracker import BeatTracker
from audio_engine.piano_analyzer import PianoAudioAnalyzer
from audio_engine.chord_detector import ChordDetector
from audio_engine.role_separator import MelodyAccompanimentSeparator

__all__ = [
    "AudioNormalizer",
    "NormalizedAudio",
    "InstrumentClassifier",
    "AudioSegmenter",
    "OnsetDetector",
    "PitchExtractor",
    "PolyphonicDecoder",
    "BeatTracker",
    "PianoAudioAnalyzer",
    "ChordDetector",
    "MelodyAccompanimentSeparator",
]
