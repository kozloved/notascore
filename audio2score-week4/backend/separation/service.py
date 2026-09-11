"""Select a separator. Default is the disabled RoFormer adapter (no fake stems)."""

from __future__ import annotations

from separation.roformer import RoFormerSeparator


def get_separator():
    return RoFormerSeparator()
