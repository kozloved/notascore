import os
import statistics
from pathlib import Path

import numpy as np
from music21 import converter, tempo as m21tempo


class TranscriptionError(Exception):
    pass


# Allow straight (16th, via 4) and eighth-note triplets (via 3) so genuine
# triplets survive, while an accurate tempo keeps straight passages triplet-free.
QUANTIZE_DIVISORS = (4, 3)

DEFAULT_TEMPO = 120.0
MIN_TEMPO = 40.0
MAX_TEMPO = 200.0
ALLOWED_MODES = ("fast", "quality")
DEFAULT_FAST_QUEUE_TIMEOUT = 600

# Classic (Maelzel) metronome graduations, used to snap the *printed* tempo to a
# conventional value.
STANDARD_TEMPOS = (
    40, 42, 44, 46, 48, 50, 52, 54, 56, 58, 60, 63, 66, 69, 72, 76, 80, 84, 88,
    92, 96, 100, 104, 108, 112, 116, 120, 126, 132, 138, 144, 152, 160, 168,
    176, 184, 192, 200, 208,
)


def snap_to_standard_tempo(bpm: float) -> int:
    """Snap a tempo to the nearest conventional metronome value (for display)."""
    return min(STANDARD_TEMPOS, key=lambda value: abs(value - bpm))


def _env_enabled(name: str, *, default: bool = True) -> bool:
    default_str = "1" if default else "0"
    return os.getenv(name, default_str).lower() in ("1", "true", "yes")


def _use_midi_cleaner() -> bool:
    return _env_enabled("TRANSCRIPTION_USE_CLEANER", default=False)


def _use_normalizer() -> bool:
    return _env_enabled("TRANSCRIPTION_USE_NORMALIZER", default=True)


def _use_beat_tracker() -> bool:
    return _env_enabled("TRANSCRIPTION_USE_BEAT_TRACKER", default=True)


def _use_piano_analyzer() -> bool:
    return _env_enabled("TRANSCRIPTION_USE_PIANO_ANALYZER", default=True)


def _should_analyze_piano(instrument) -> bool:
    """Fast path is poly piano; skip only obvious non-piano families."""
    if not _use_piano_analyzer():
        return False
    from mir.types import InstrumentKind

    return instrument not in (InstrumentKind.DRUMS, InstrumentKind.VOICE)


def detect_tempo(audio_path) -> float:
    """Rough tempo estimate (BPM) from the audio, folded into a musical range."""
    try:
        import librosa

        y, sr = librosa.load(str(audio_path), mono=True)

        try:
            estimate = librosa.feature.rhythm.tempo(y=y, sr=sr)
        except AttributeError:
            estimate = librosa.beat.tempo(y=y, sr=sr)

        bpm = float(estimate[0]) if len(estimate) else DEFAULT_TEMPO
    except Exception:
        return DEFAULT_TEMPO

    if not bpm or bpm != bpm or bpm <= 0:
        return DEFAULT_TEMPO

    while bpm < MIN_TEMPO:
        bpm *= 2
    while bpm > MAX_TEMPO:
        bpm /= 2

    return float(bpm)


def refine_tempo(onsets, base_bpm: float) -> float:
    """Refine the tempo so note onsets best line up with a beat grid."""
    onsets = np.asarray(sorted(float(o) for o in onsets), dtype=float)
    if onsets.size < 6:
        return round(base_bpm, 2)

    onsets = onsets - onsets[0]
    onsets = onsets[onsets > 1e-6]
    if onsets.size < 4:
        return round(base_bpm, 2)

    best_bpm, best_err = base_bpm, float("inf")

    for factor in (0.5, 2.0 / 3.0, 0.8, 1.0, 1.25, 1.5, 2.0):
        center = base_bpm * factor
        for bpm in np.arange(center - 8.0, center + 8.0, 0.05):
            if bpm < MIN_TEMPO or bpm > MAX_TEMPO:
                continue
            quarter = 60.0 / bpm
            sixteenth = quarter / 4.0
            err16 = float(np.mean(np.abs(onsets / sixteenth - np.round(onsets / sixteenth))))
            errq = float(np.mean(np.abs(onsets / quarter - np.round(onsets / quarter))))
            err = err16 + 0.5 * errq + 0.002 * abs(bpm - base_bpm) / max(base_bpm, 1.0)
            if err < best_err:
                best_err, best_bpm = err, float(bpm)

    return float(round(best_bpm, 2))


def _estimate_tempo(audio_path: Path, onsets: list[float]) -> float:
    """Seed tempo from beat tracker when enabled, else librosa on file."""
    if _use_beat_tracker():
        from audio_engine.beat_tracker import BeatTracker
        from audio_engine.normalizer import AudioNormalizer

        normalized = AudioNormalizer().normalize(audio_path)
        tracker = BeatTracker()
        seed = tracker.track(normalized).bpm_at(0.0)
        if tracker.last_source == "madmom":
            return round(seed, 2)
    else:
        seed = detect_tempo(audio_path)

    return refine_tempo(onsets, seed)


class BasicPitchEngine:
    name = "basic_pitch"

    def transcribe(self, audio_path, job_id):
        from mir.midi_ingest import is_midi_path

        audio_path = Path(audio_path)
        if is_midi_path(audio_path):
            from mir.pipeline import UnderstandingPipeline

            return UnderstandingPipeline().transcribe(audio_path, job_id)

        import pretty_midi

        from adapters.basic_pitch_backend import BasicPitchBackend
        from audio_engine.instrument_classifier import InstrumentClassifier
        from audio_engine.normalizer import AudioNormalizer
        from audio_engine.piano_analyzer import PianoAudioAnalyzer
        from mir.midi_cleaner import MIDICleaner
        from mir.raw_midi import write_job_raw_midi
        from mir.types import InstrumentKind

        audio_path = Path(audio_path)
        out_dir = audio_path.parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)

        transcribe_path = audio_path
        normalized = None
        instrument = InstrumentKind.UNKNOWN

        if _use_normalizer() or _use_piano_analyzer():
            normalizer = AudioNormalizer()
            normalized = normalizer.normalize(audio_path)
            if _use_normalizer():
                transcribe_path = normalizer.write_wav(
                    normalized, out_dir / f"{job_id}_norm.wav"
                )
            if _use_piano_analyzer():
                prediction = InstrumentClassifier().classify(normalized)
                instrument = prediction.instrument

        backend = BasicPitchBackend()
        note_events = backend.transcribe_notes(transcribe_path)
        raw_count = len(note_events)

        if _use_midi_cleaner():
            note_events = MIDICleaner().clean(note_events)
            print(
                f"[MIDICleaner] notes {raw_count} → {len(note_events)} "
                f"(job={job_id})"
            )
        elif os.getenv("TRANSCRIPTION_SHADOW_CLEANER", "").lower() in (
            "1",
            "true",
            "yes",
        ):
            shadowed = MIDICleaner().clean(note_events)
            print(
                f"[MIDICleaner shadow] would change notes "
                f"{raw_count} → {len(shadowed)} (job={job_id})"
            )

        pedal_events: list[tuple[float, int]] = []
        if _should_analyze_piano(instrument) and normalized is not None:
            piano = PianoAudioAnalyzer().analyze(normalized, note_events)
            note_events = piano.notes
            pedal_events = [(p.time_sec, p.value) for p in piano.pedal_events]
            print(
                f"[PianoAnalyzer] refined velocities for {len(note_events)} notes "
                f"(job={job_id})"
            )

        onsets = [n.start_time for n in note_events]
        if not onsets:
            raise TranscriptionError("No notes detected")

        bpm = _estimate_tempo(audio_path, onsets)
        write_job_raw_midi(
            audio_path,
            job_id,
            note_events,
            bpm=bpm,
            pedal_events=pedal_events,
            split_hands=True,
        )
        print(
            f"[EnhancedLegacy] instrument={instrument.value} tempo={bpm:.1f} "
            f"notes={len(note_events)} normalizer={_use_normalizer()} "
            f"beat_tracker={_use_beat_tracker()} (job={job_id})"
        )

        aligned = pretty_midi.PrettyMIDI(initial_tempo=bpm)
        inst = pretty_midi.Instrument(program=0)
        for n in note_events:
            inst.notes.append(
                pretty_midi.Note(
                    velocity=n.velocity,
                    pitch=n.pitch,
                    start=n.start_time,
                    end=n.end_time,
                )
            )
        aligned.instruments.append(inst)

        all_notes = list(inst.notes)
        if len(all_notes) >= 3:
            last = max(all_notes, key=lambda n: n.start)
            typical = statistics.median(
                n.end - n.start for n in all_notes if n is not last
            )
            if (last.end - last.start) < typical:
                last.end = last.start + typical

        midi_path = out_dir / f"{job_id}.mid"
        aligned.write(str(midi_path))

        score = converter.parse(str(midi_path))
        score.quantize(
            quarterLengthDivisors=QUANTIZE_DIVISORS,
            processOffsets=True,
            processDurations=True,
            inPlace=True,
            recurse=True,
        )

        display_bpm = snap_to_standard_tempo(bpm)
        marks = list(score.recurse().getElementsByClass(m21tempo.MetronomeMark))
        if marks:
            for mark in marks:
                mark.number = display_bpm
        else:
            score.insert(0, m21tempo.MetronomeMark(number=display_bpm))

        xml_path = out_dir / f"{job_id}.musicxml"
        score.write("musicxml", fp=str(xml_path))
        score.write("midi", fp=str(out_dir / f"{job_id}.score.mid"))

        return xml_path.read_text(encoding="utf-8")


class FallbackEngine:
    """Run understanding pipeline with legacy fallback on failure."""

    name = "understanding"

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback

    def transcribe(self, audio_path, job_id):
        from mir.midi_ingest import is_midi_path

        if is_midi_path(audio_path):
            return self.primary.transcribe(audio_path, job_id)
        try:
            return self.primary.transcribe(audio_path, job_id)
        except Exception as exc:
            print(
                f"[PipelineFallback] understanding failed ({exc!s}), "
                f"using legacy (job={job_id})"
            )
            return self.fallback.transcribe(audio_path, job_id)


def parse_transcription_mode(mode: str | None) -> str:
    """Return 'fast' or 'quality'. Invalid values raise ValueError."""
    value = (mode or "fast").strip().lower()
    if value not in ALLOWED_MODES:
        raise ValueError("Invalid transcription mode. Use 'fast' or 'quality'.")
    return value


def queue_timeout_for_mode(mode: str) -> int:
    """RQ job_timeout: Quality waits on a remote GPU, so it needs more room."""
    resolved = parse_transcription_mode(mode)
    if resolved != "quality":
        return DEFAULT_FAST_QUEUE_TIMEOUT
    from adapters.mt3_backend import mt3_settings

    return max(900, int(mt3_settings()["timeout"]) + 120)


def get_engine(mode: str | None = None, filename: str | None = None):
    from mir.midi_ingest import is_midi_path

    if filename and is_midi_path(filename):
        from mir.pipeline import UnderstandingPipeline

        return UnderstandingPipeline()

    resolved = parse_transcription_mode(mode)
    if resolved == "quality":
        from adapters.mt3_backend import MT3Backend, mt3_available
        from mir.pipeline import UnderstandingPipeline

        if not mt3_available():
            raise TranscriptionError(
                "Quality mode (MT3) is not configured. "
                "Set MT3_ENDPOINT or MT3_TRANSCRIBE_COMMAND."
            )
        # Quality never falls back to Fast / Basic Pitch.
        return UnderstandingPipeline(backend_name=MT3Backend.name, mode="quality")

    pipeline = os.getenv("TRANSCRIPTION_PIPELINE", "understanding").lower()
    if pipeline == "understanding":
        from mir.pipeline import UnderstandingPipeline

        primary = UnderstandingPipeline(mode=resolved)
        if _env_enabled("TRANSCRIPTION_PIPELINE_FALLBACK", default=True):
            return FallbackEngine(primary, BasicPitchEngine())
        return primary
    return BasicPitchEngine()
