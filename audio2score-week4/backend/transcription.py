
from pathlib import Path
from music21 import converter
from basic_pitch import FilenameSuffix, build_icassp_2022_model_path
from basic_pitch.inference import predict_and_save

class TranscriptionError(Exception):
    pass

class BasicPitchEngine:
    name = "basic_pitch"

    def transcribe(self, audio_path, job_id):
        audio_path = Path(audio_path)
        out_dir = audio_path.parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)

        # Prefer ONNX so RQ's forked work-horse avoids CoreML/objc on macOS.
        model_path = build_icassp_2022_model_path(FilenameSuffix.onnx)

        predict_and_save(
            audio_path_list=[str(audio_path)],
            output_directory=str(out_dir),
            save_midi=True,
            sonify_midi=False,
            save_model_outputs=False,
            save_notes=False,
            model_or_model_path=model_path,
        )

        midi_files = list(out_dir.glob("*.mid"))
        if not midi_files:
            raise TranscriptionError("No MIDI generated")

        score = converter.parse(str(midi_files[0]))
        xml_path = out_dir / f"{job_id}.musicxml"
        score.write("musicxml", fp=str(xml_path))

        return xml_path.read_text(encoding="utf-8")

def get_engine():
    return BasicPitchEngine()
