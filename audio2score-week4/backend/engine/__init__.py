"""Next-gen pipeline façade. Wraps existing MIR/notation; does not replace it."""

from engine.artifacts import ArtifactManifest, ArtifactRef
from engine.ir import InterpretedNote, InterpretedPerformance, NoteEvidence
from engine.stages import StageName, StageResult

__all__ = [
    "ArtifactManifest",
    "ArtifactRef",
    "InterpretedNote",
    "InterpretedPerformance",
    "NoteEvidence",
    "StageName",
    "StageResult",
]
