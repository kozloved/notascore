"""Heuristic instrument classification from spectral features."""

from __future__ import annotations

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import InstrumentCharacteristics, InstrumentKind, InstrumentPrediction


class InstrumentClassifier:
    """Classify instrument family before choosing transcription strategy."""

    def classify(self, audio: NormalizedAudio) -> InstrumentPrediction:
        import librosa

        y = audio.samples
        sr = audio.sample_rate
        if y.size < sr // 10:
            return InstrumentPrediction(
                instrument=InstrumentKind.UNKNOWN,
                confidence=0.0,
            )

        centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
        rolloff = float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr)))
        zcr = float(np.mean(librosa.feature.zero_crossing_rate(y)))

        y_harm, y_perc = librosa.effects.hpss(y)
        harm_energy = float(np.sum(y_harm**2))
        perc_energy = float(np.sum(y_perc**2))
        hp_ratio = harm_energy / (harm_energy + perc_energy + 1e-8)

        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        pitch_entropy = float(
            -np.sum(chroma * np.log(chroma + 1e-8)) / max(chroma.shape[1], 1)
        )

        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        attack = float(np.mean(onset_env))

        pitch_min, pitch_max = self._estimate_pitch_range(y, sr)
        pitch_range = pitch_max - pitch_min

        characteristics = InstrumentCharacteristics(
            polyphony=min(1.0, pitch_entropy / 4.0),
            pitch_range_semitones=float(pitch_range),
            attack_profile=min(1.0, attack / 10.0),
            sustain_profile=min(1.0, hp_ratio),
        )

        scores = {
            InstrumentKind.PIANO: 0.0,
            InstrumentKind.VOICE: 0.0,
            InstrumentKind.DRUMS: 0.0,
            InstrumentKind.GUITAR: 0.0,
            InstrumentKind.STRINGS: 0.0,
        }

        # Piano: harmonic, wide range, moderate polyphony
        scores[InstrumentKind.PIANO] = (
            hp_ratio * 0.4
            + min(1.0, pitch_range / 48) * 0.3
            + min(1.0, characteristics.polyphony) * 0.3
        )
        # Voice: narrow range, low polyphony
        scores[InstrumentKind.VOICE] = (
            (1.0 - min(1.0, characteristics.polyphony)) * 0.5
            + (1.0 - min(1.0, pitch_range / 24)) * 0.3
            + min(1.0, zcr * 10) * 0.2
        )
        # Drums: percussive, low harmonic ratio
        scores[InstrumentKind.DRUMS] = (
            (1.0 - hp_ratio) * 0.6 + min(1.0, attack / 8) * 0.4
        )
        # Guitar: mid centroid, moderate range
        scores[InstrumentKind.GUITAR] = (
            min(1.0, centroid / 3000) * 0.3
            + min(1.0, pitch_range / 36) * 0.4
            + hp_ratio * 0.3
        )
        # Strings: high sustain, wide range
        scores[InstrumentKind.STRINGS] = (
            hp_ratio * 0.3
            + min(1.0, pitch_range / 40) * 0.4
            + min(1.0, rolloff / 8000) * 0.3
        )

        best = max(scores, key=scores.get)
        confidence = scores[best]
        if confidence < 0.35:
            return InstrumentPrediction(
                instrument=InstrumentKind.UNKNOWN,
                confidence=confidence,
                characteristics=characteristics,
            )

        return InstrumentPrediction(
            instrument=best,
            confidence=min(1.0, confidence),
            characteristics=characteristics,
        )

    def _estimate_pitch_range(self, y: np.ndarray, sr: int) -> tuple[float, float]:
        import librosa

        pitches, _ = librosa.piptrack(y=y, sr=sr)
        valid = pitches[pitches > 0]
        if valid.size == 0:
            return 48.0, 72.0
        midi = librosa.hz_to_midi(valid)
        return float(np.min(midi)), float(np.max(midi))
