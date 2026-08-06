
import statistics
from pathlib import Path

import numpy as np
from music21 import converter, tempo as m21tempo
from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict


class TranscriptionError(Exception):
    pass


# Allow straight (16th, via 4) and eighth-note triplets (via 3) so genuine
# triplets survive, while an accurate tempo keeps straight passages triplet-free.
QUANTIZE_DIVISORS = (4, 3)

DEFAULT_TEMPO = 120.0
MIN_TEMPO = 50.0
MAX_TEMPO = 200.0


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
    """Refine the tempo so note onsets best line up with a beat grid.

    A rough global tempo estimate can be off by a couple of BPM. Because
    quantization snaps *absolute* note positions, that small error accumulates
    and later notes drift off the beat. Here we search tempos near the estimate
    (and its half/double) and pick the one that makes the onsets fall closest to
    a sixteenth-note grid, which removes the drift.
    """
    onsets = np.asarray(sorted(float(o) for o in onsets), dtype=float)
    if onsets.size < 6:
        return round(base_bpm, 2)

    onsets = onsets - onsets[0]
    onsets = onsets[onsets > 1e-6]
    if onsets.size < 4:
        return round(base_bpm, 2)

    best_bpm, best_err = base_bpm, float("inf")

    for center in {base_bpm * 0.5, base_bpm, base_bpm * 2.0}:
        for bpm in np.arange(center - 8.0, center + 8.0, 0.05):
            if bpm < MIN_TEMPO or bpm > MAX_TEMPO:
                continue
            grid = (60.0 / bpm) / 4.0  # sixteenth-note spacing in seconds
            ratio = onsets / grid
            # Mean distance to the nearest grid line, as a fraction of a cell.
            err = float(np.mean(np.abs(ratio - np.round(ratio))))
            if err < best_err:
                best_err, best_bpm = err, float(bpm)

    return float(round(best_bpm, 2))


class BasicPitchEngine:
    name = "basic_pitch"

    def transcribe(self, audio_path, job_id):
        import pretty_midi

        audio_path = Path(audio_path)
        out_dir = audio_path.parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)

        # Single model inference; gives us the notes (with times in seconds).
        _, midi_data, _ = predict(
            str(audio_path),
            model_or_model_path=ICASSP_2022_MODEL_PATH,
        )

        onsets = [note.start for inst in midi_data.instruments for note in inst.notes]
        if not onsets:
            raise TranscriptionError("No notes detected")

        bpm = refine_tempo(onsets, detect_tempo(audio_path))

        # Re-emit the MIDI at the refined tempo. Note times stay in seconds, so
        # they now map onto a beat grid that matches the music (no drift).
        aligned = pretty_midi.PrettyMIDI(initial_tempo=bpm)
        for inst in midi_data.instruments:
            new_inst = pretty_midi.Instrument(
                program=inst.program,
                is_drum=inst.is_drum,
                name=inst.name,
            )
            new_inst.notes = list(inst.notes)
            aligned.instruments.append(new_inst)

        # Basic Pitch tends to clip the final note (the audio just stops), so it
        # ends up shorter than the rest. If the last note is shorter than the
        # typical (median) note, stretch it to that length so the piece doesn't
        # end on an oddly short note.
        all_notes = [note for inst in aligned.instruments for note in inst.notes]
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

        # Quantize onsets AND durations. With an accurate tempo the triplet grid
        # is only chosen for notes that genuinely fall on it.
        score.quantize(
            quarterLengthDivisors=QUANTIZE_DIVISORS,
            processOffsets=True,
            processDurations=True,
            inPlace=True,
            recurse=True,
        )

        # Show a clean, rounded tempo on the sheet for readability. This only
        # changes the printed marking — the precise tempo above is what drove the
        # quantization/alignment, so the notes themselves are unaffected.
        display_bpm = int(round(bpm))
        marks = list(score.recurse().getElementsByClass(m21tempo.MetronomeMark))
        if marks:
            for mark in marks:
                mark.number = display_bpm
        else:
            score.insert(0, m21tempo.MetronomeMark(number=display_bpm))

        xml_path = out_dir / f"{job_id}.musicxml"
        score.write("musicxml", fp=str(xml_path))

        return xml_path.read_text(encoding="utf-8")


def get_engine():
    return BasicPitchEngine()
