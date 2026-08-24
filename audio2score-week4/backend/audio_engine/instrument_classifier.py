"""Heuristic instrument classification from spectral features."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import InstrumentCharacteristics, InstrumentKind, InstrumentPrediction

# Fast mode is polyphonic piano: guitar only wins with a clear margin.
_GUITAR_MARGIN = 0.06
_UNKNOWN_FLOOR = 0.35


@dataclass
class _Features:
    centroid: float
    hp_ratio: float
    zcr: float
    polyphony: float
    n_peaks: float
    pitch_range: float
    attack: float
    low_ratio: float
    high_ratio: float
    decay: float
    f0_mod: float


class InstrumentClassifier:
    """Classify instrument family before choosing transcription strategy."""

    def classify(self, audio: NormalizedAudio) -> InstrumentPrediction:
        y = audio.samples
        sr = audio.sample_rate
        if y.size < sr // 10:
            return InstrumentPrediction(
                instrument=InstrumentKind.UNKNOWN,
                confidence=0.0,
            )

        feats = self._features(y, sr)
        characteristics = InstrumentCharacteristics(
            polyphony=min(1.0, feats.polyphony),
            pitch_range_semitones=float(feats.pitch_range),
            attack_profile=min(1.0, feats.attack / 10.0),
            sustain_profile=min(1.0, feats.hp_ratio),
        )

        if self._is_simple_tone(feats):
            return InstrumentPrediction(
                instrument=InstrumentKind.UNKNOWN,
                confidence=0.2,
                characteristics=characteristics,
            )

        scores = self._scores(feats)
        tags = self._audioset_prior(audio)
        if tags is not None:
            for kind, score in tags.scores.items():
                if kind in scores:
                    scores[kind] = 0.7 * float(scores[kind]) + 0.3 * float(score)
        best = max(scores, key=scores.get)
        if (
            best == InstrumentKind.GUITAR
            and scores[InstrumentKind.PIANO] + _GUITAR_MARGIN >= scores[best]
        ):
            best = InstrumentKind.PIANO

        second = max(
            (score for kind, score in scores.items() if kind != best),
            default=0.0,
        )
        margin = max(0.0, scores[best] - second)
        confidence = min(1.0, 0.55 * float(scores[best]) + 0.45 * min(1.0, margin / 0.25))

        if confidence < _UNKNOWN_FLOOR:
            return InstrumentPrediction(
                instrument=InstrumentKind.UNKNOWN,
                confidence=confidence,
                characteristics=characteristics,
            )

        return InstrumentPrediction(
            instrument=best,
            confidence=confidence,
            characteristics=characteristics,
        )

    def _features(self, y: np.ndarray, sr: int) -> _Features:
        import librosa

        centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
        zcr = float(np.mean(librosa.feature.zero_crossing_rate(y)))

        y_harm, y_perc = librosa.effects.hpss(y)
        harm_energy = float(np.sum(y_harm**2))
        perc_energy = float(np.sum(y_perc**2))
        hp_ratio = harm_energy / (harm_energy + perc_energy + 1e-8)

        spec = np.abs(librosa.stft(y)) ** 2
        freqs = librosa.fft_frequencies(sr=sr)
        total = float(np.sum(spec)) + 1e-8
        low_ratio = float(np.sum(spec[freqs < 120.0]) / total)
        high_ratio = float(np.sum(spec[freqs >= 2000.0]) / total)

        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        attack = float(np.mean(onset_env))

        rms = librosa.feature.rms(y=y)[0]
        decay = 0.0
        if rms.size >= 4:
            peak = int(np.argmax(rms))
            tail = rms[peak:] + 1e-8
            if tail.size >= 4:
                slope = float(np.polyfit(np.arange(tail.size), np.log(tail), 1)[0])
                hop = 512
                decay = max(0.0, -slope * (sr / hop))

        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        peak_mask = chroma > 0.45 * np.maximum(chroma.max(axis=0, keepdims=True), 1e-8)
        n_peaks = float(np.mean(peak_mask.sum(axis=0)))
        pitch_entropy = float(
            -np.sum(chroma * np.log(chroma + 1e-8)) / max(chroma.shape[1], 1)
        )
        polyphony = min(1.0, max(pitch_entropy / 4.0, (n_peaks - 1.0) / 3.0))

        pitches, mags = librosa.piptrack(y=y, sr=sr)
        idx = np.argmax(mags, axis=0)
        cols = np.arange(pitches.shape[1])
        f0 = pitches[idx, cols]
        mag = mags[idx, cols]
        mag_cut = float(np.median(mag) * 0.5) if mag.size else 0.0
        voiced = f0[(f0 > 0) & (mag > mag_cut)]
        if voiced.size > 4:
            midi = librosa.hz_to_midi(voiced)
            cents = 1200.0 * np.log2(voiced / np.median(voiced))
            f0_mod = float(np.std(cents))
            pitch_range = float(np.percentile(midi, 90) - np.percentile(midi, 10))
        else:
            f0_mod = 0.0
            pitch_range = 0.0
        strong = pitches[mags > max(float(np.median(mags)) * 2.0, 1e-4)]
        if strong.size > 8:
            midi_all = librosa.hz_to_midi(strong)
            pitch_range = max(
                pitch_range,
                float(np.percentile(midi_all, 90) - np.percentile(midi_all, 10)),
            )

        return _Features(
            centroid=centroid,
            hp_ratio=hp_ratio,
            zcr=zcr,
            polyphony=polyphony,
            n_peaks=n_peaks,
            pitch_range=pitch_range,
            attack=attack,
            low_ratio=low_ratio,
            high_ratio=high_ratio,
            decay=decay,
            f0_mod=f0_mod,
        )

    @staticmethod
    def _audioset_prior(audio: NormalizedAudio):
        try:
            from audio_engine.audioset_tagger import tag_audio

            return tag_audio(audio)
        except Exception:
            return None

    @staticmethod
    def _is_simple_tone(feats: _Features) -> bool:
        """Stable single-pitch sines are not voice or guitar."""
        return (
            feats.n_peaks <= 1.25
            and feats.f0_mod < 8.0
            and feats.high_ratio < 0.03
            and feats.low_ratio < 0.05
            and feats.hp_ratio > 0.95
            and feats.pitch_range < 6.0
        )

    @staticmethod
    def _scores(feats: _Features) -> dict[InstrumentKind, float]:
        guitar_range = _triangle(feats.pitch_range, peak=32.0, width=28.0)

        piano = (
            feats.hp_ratio * 0.22
            + min(1.0, feats.polyphony) * 0.22
            + min(1.0, feats.n_peaks / 3.0) * 0.12
            + min(1.0, feats.pitch_range / 48.0) * 0.12
            + min(1.0, feats.low_ratio / 0.15) * 0.16
            + (1.0 - min(1.0, feats.decay / 6.0)) * 0.08
            + 0.10  # Fast-mode piano prior
        )
        guitar = (
            min(1.0, feats.decay / 5.0) * 0.28
            + min(1.0, feats.high_ratio / 0.08) * 0.32
            + (1.0 - min(1.0, feats.low_ratio / 0.12)) * 0.18
            + guitar_range * 0.12
            + min(1.0, feats.centroid / 3500.0) * 0.10
        )
        drums = (1.0 - feats.hp_ratio) * 0.65 + min(1.0, feats.attack / 8.0) * 0.35
        strings = (
            feats.hp_ratio * 0.35
            + min(1.0, feats.pitch_range / 40.0) * 0.25
            + (1.0 - min(1.0, feats.decay / 4.0)) * 0.25
            + min(1.0, feats.high_ratio / 0.05) * 0.15
        )
        if feats.n_peaks < 1.4 or feats.pitch_range < 20.0:
            strings *= 0.35

        voice = 0.0
        vocal = (
            feats.n_peaks < 1.35
            and 8.0 <= feats.f0_mod <= 90.0
            and feats.pitch_range < 28.0
            and feats.hp_ratio > 0.7
            and feats.polyphony < 0.45
        )
        if vocal:
            voice = (
                0.50
                + min(1.0, feats.f0_mod / 40.0) * 0.30
                + (1.0 - min(1.0, feats.pitch_range / 24.0)) * 0.20
            )

        return {
            InstrumentKind.PIANO: piano,
            InstrumentKind.GUITAR: guitar,
            InstrumentKind.VOICE: voice,
            InstrumentKind.DRUMS: drums,
            InstrumentKind.STRINGS: strings,
        }


def _triangle(value: float, peak: float, width: float) -> float:
    return float(max(0.0, 1.0 - abs(value - peak) / width))
