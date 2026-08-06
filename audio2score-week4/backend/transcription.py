
from pathlib import Path

from music21 import converter, tempo as m21tempo
from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict_and_save


class TranscriptionError(Exception):
    pass


# Snap note starts/ends to an 8th/16th-note grid (no triplets) so the engraved
# rhythm stays readable instead of a mess of tuplets and tied fractions.
QUANTIZE_DIVISORS = (4, 2)

DEFAULT_TEMPO = 120.0
MIN_TEMPO = 50.0
MAX_TEMPO = 200.0


def detect_tempo(audio_path) -> float:
    """Estimate the tempo (BPM) of the audio, folded into a musical range.

    Falls back to a sensible default if estimation fails.
    """
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

    # Guard against NaN / non-positive values.
    if not bpm or bpm != bpm or bpm <= 0:
        return DEFAULT_TEMPO

    # Fold octave errors (e.g. 47 -> 94, 220 -> 110) into a musical range.
    while bpm < MIN_TEMPO:
        bpm *= 2
    while bpm > MAX_TEMPO:
        bpm /= 2

    return float(round(bpm))


class BasicPitchEngine:
    name = "basic_pitch"

    def transcribe(self, audio_path, job_id):
        audio_path = Path(audio_path)
        out_dir = audio_path.parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)

        bpm = detect_tempo(audio_path)

        # Write the MIDI at the detected tempo so its beat grid lines up with
        # the music, which makes the quantization below meaningful.
        predict_and_save(
            audio_path_list=[str(audio_path)],
            output_directory=str(out_dir),
            save_midi=True,
            sonify_midi=False,
            save_model_outputs=False,
            save_notes=False,
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            midi_tempo=bpm,
        )

        midi_files = list(out_dir.glob("*.mid"))
        if not midi_files:
            raise TranscriptionError("No MIDI generated")

        score = converter.parse(str(midi_files[0]))

        # Quantize both note onsets and durations to a simple grid so the
        # notation is readable rather than full of complex tuplet rhythms.
        score.quantize(
            quarterLengthDivisors=QUANTIZE_DIVISORS,
            processOffsets=True,
            processDurations=True,
            inPlace=True,
            recurse=True,
        )

        # Ensure the detected tempo is shown on the score.
        if not score.recurse().getElementsByClass(m21tempo.MetronomeMark):
            score.insert(0, m21tempo.MetronomeMark(number=bpm))

        xml_path = out_dir / f"{job_id}.musicxml"
        score.write("musicxml", fp=str(xml_path))

        return xml_path.read_text(encoding="utf-8")


def get_engine():
    return BasicPitchEngine()
