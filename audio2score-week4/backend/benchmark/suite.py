"""Run structure + notation metrics on synthetic benchmark cases."""

from __future__ import annotations

from dataclasses import dataclass

from benchmark.cases import ALL_CASES, BenchmarkCase
from mir.hand_separator import HandSeparator
from mir.meter import MeterEstimator
from mir.types import Hand, ScoreMeta
from mir.voice_separator import VoiceSeparator
from notation_engine.plan import NotationPlanner


@dataclass
class CaseResult:
    name: str
    hand_accuracy: float | None = None
    voice_ok: bool | None = None
    meter_ok: bool | None = None
    measure_sum_ok: bool = True
    details: str = ""


def _hand_accuracy(case: BenchmarkCase) -> float | None:
    if not case.expected_hands:
        return None
    separated = HandSeparator().separate(list(case.events))
    correct = 0
    total = 0
    for ev in separated:
        expected = case.expected_hands.get(ev.pitch)
        if expected is None:
            continue
        total += 1
        if ev.hand.value == expected:
            correct += 1
    return correct / total if total else None


def _voice_ok(case: BenchmarkCase) -> bool | None:
    if case.expected_voice_count_rh is None:
        return None
    voiced = VoiceSeparator().separate(list(case.events))
    rh = [e for e in voiced if e.hand in (Hand.RIGHT, Hand.UNKNOWN, Hand.AMBIGUOUS)]
    return len({e.voice for e in rh}) == case.expected_voice_count_rh


def _meter_ok(case: BenchmarkCase) -> bool | None:
    if not case.expected_meter:
        return None
    selected = MeterEstimator().select(list(case.events)).time_signature
    if case.expected_meter == "4/4":
        return selected in ("4/4", "2/4")
    return selected == case.expected_meter


def evaluate_case(case: BenchmarkCase) -> CaseResult:
    result = CaseResult(name=case.name)
    result.hand_accuracy = _hand_accuracy(case)
    result.voice_ok = _voice_ok(case)
    result.meter_ok = _meter_ok(case)

    events = HandSeparator().separate(list(case.events))
    events = VoiceSeparator().separate(events)
    plan, _ = NotationPlanner().build(events, meta=ScoreMeta(display_tempo_bpm=120))
    for measure in plan.measures:
        for staff in measure.staves:
            for voice in staff.voices:
                total = sum(el.duration_q for el in voice.elements)
                if abs(total - measure.duration_beats) > 0.15:
                    result.measure_sum_ok = False
    return result


def run_suite() -> list[CaseResult]:
    return [evaluate_case(case) for case in ALL_CASES]


def passed(result: CaseResult) -> bool:
    if result.hand_accuracy is not None and result.hand_accuracy < 0.85:
        return False
    if result.voice_ok is False:
        return False
    if result.meter_ok is False:
        return False
    if not result.measure_sum_ok:
        return False
    return True
