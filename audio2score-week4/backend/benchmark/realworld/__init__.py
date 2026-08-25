"""Local real-world evaluation corpus (manifest-driven, audio not git-tracked)."""

from benchmark.realworld.schema import RealWorldCase, load_manifest

__all__ = ["RealWorldCase", "load_manifest"]
