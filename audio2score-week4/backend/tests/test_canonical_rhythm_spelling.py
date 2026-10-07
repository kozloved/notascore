"""Canonical spelling must not introduce a new rhythmic family."""
from fractions import Fraction as F
import pytest
from notation_engine.exact_plan import _pieces
from mir.notation_settings import NotationSettings


@pytest.mark.parametrize("policy", ["preserve", "show_meter"])
@pytest.mark.parametrize("dots", [0, 1, 2])
def test_binary_spans_never_invent_tuplets(policy, dots):
    settings = NotationSettings.from_dict({"syncopation": policy, "max_dots": dots})
    for start in (F(0), F(1, 8), F(1, 2)):
        for ticks in range(1, 49):
            duration = F(ticks, 16)
            pieces = list(_pieces(start, duration, settings=settings, measure_length=F(4)))
            assert sum(length for _, length in pieces) == duration
            cursor = start
            for offset, length in pieces:
                assert offset == cursor
                assert length > 0
                assert length.denominator & (length.denominator - 1) == 0
                cursor += length


def test_eleven_eighths_uses_simple_binary_ties():
    assert list(_pieces(F(0), F(11, 8))) == [(F(0), F(1)), (F(1), F(3, 8))]


@pytest.mark.parametrize("start,duration", [(F(0), F(1, 3)), (F(1, 3), F(2, 3))])
def test_genuine_triplets_keep_exact_spelling(start, duration):
    assert list(_pieces(start, duration)) == [(start, duration)]
