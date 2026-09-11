"""Bounded performance-to-score inference with immutable source provenance.

Tempo and meter remain upstream hypotheses. Rhythm search consumes assigned
hands/voices when present; unlabeled piano still infers a layout.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
from fractions import Fraction
from math import isfinite
from statistics import mean

from mir.hand_separator import HandSeparator
from mir.models import staff_for_hand
from mir.score_profile import ScoreProfile, score_profile
from mir.types import Hand, copy_event
from mir.voice_separator import VoiceSeparator

_ASSIGNED_HANDS = {Hand.LEFT, Hand.RIGHT, Hand.AMBIGUOUS}


@dataclass(frozen=True)
class ScoreNote:
    source_id: str
    onset: Fraction
    duration: Fraction
    voice: int
    staff: int
    role: str
    rhythm_family: str
    group_id: str


@dataclass
class PerformanceReport:
    summary: dict
    notes: tuple[ScoreNote, ...]
    decisions: list[dict]


def _onset_candidates(raw, max_move):
    candidates = {}
    for denominator, family, complexity in (
        (1, "binary", 0.0), (2, "binary", 0.008),
        (4, "binary", 0.016), (8, "binary", 0.035),
        (3, "triplet", 0.035), (6, "triplet", 0.05),
        (16, "binary", 0.08),
    ):
        center = round(raw * denominator)
        for tick in range(center - 1, center + 2):
            onset = Fraction(tick, denominator)
            error = abs(float(onset) - raw)
            if onset < 0 or error > max_move:
                continue
            # Performance jitter is not evidence for a 32nd/64th or a tuplet.
            # Keep the full vocabulary for genuinely distinct fast attacks;
            # prefer simpler values inside a small, bounded timing tolerance.
            tolerance = 0.065 if family == "binary" and denominator <= 4 else 0.0
            cost = max(0.0, error - tolerance) * 3 + complexity
            key = (onset, family)
            if key not in candidates or cost < candidates[key]:
                candidates[key] = cost
    if not candidates:
        raise ValueError(f"No readable onset within timing bound at {raw}")
    return [(onset, family, cost) for (onset, family), cost in candidates.items()]


def _search(groups, max_move, beam_width=24):
    # State includes the previous interval so recurring figures favor the same
    # interpretation. Strict ordering is a constraint, never a repair pass.
    beam = [(0.0, (), None)]
    for group in groups:
        raw = mean(e.start_beat for e in group)
        next_beam = []
        for cost, path, last_interval in beam:
            for onset, family, local_cost in _onset_candidates(raw, max_move):
                if any(abs(float(onset) - ev.start_beat) > max_move for ev in group):
                    continue
                if path and onset <= path[-1][0]:
                    continue
                interval = onset - path[-1][0] if path else None
                transition = 0.0
                if path and family != path[-1][1] and onset.denominator != 1:
                    transition += 0.025
                if last_interval is not None and interval != last_interval:
                    transition += 0.008
                next_beam.append((cost + local_cost + transition,
                                  path + ((onset, family),), interval))
        if not next_beam:
            raise ValueError("Distinct attacks cannot fit the supported rhythm vocabulary")
        beam = sorted(next_beam, key=lambda state: state[0])[:beam_width]
    return beam[0][1]


def _duration(raw, onset, next_onset, overlaps, family):
    unit = Fraction(1, 6) if family == "triplet" else Fraction(1, 16)
    named = {Fraction(n, d) for d in (1, 2, 4, 8, 16)
             for n in (1, 2, 3, 4, 6, 8, 12, 16)}
    if family == "triplet":
        named.update(Fraction(n, 6) for n in (1, 2, 4, 8, 16))
    # Long sustains remain possible and will be split into barline ties.
    named.add(max(unit, round(raw / float(unit)) * unit))
    if next_onset is not None and not overlaps:
        cap = next_onset - onset
        named = {d for d in named if d <= cap}
        if cap > 0:
            named.add(cap)
    tolerance = min(0.10, raw * 0.20)
    close = {d for d in named if abs(float(d) - raw) <= tolerance + 1e-9}
    if close:
        # Prefer one named value to a chain of tiny tied fragments. For
        # example, a 0.94-beat release is a quarter, not 15/16 + a tiny rest.
        def spelling_cost(d):
            numerator = d.numerator
            while numerator % 2 == 0:
                numerator //= 2
            return (numerator not in (1, 3), d.denominator,
                    abs(float(d) - raw), d)
        return min(close, key=spelling_cost)
    return min(named, key=lambda d: (abs(float(d) - raw), d.denominator, d))


def _stable_lanes(events, exact, grand_staff=True):
    """Allocate over the entire piece so tied notes keep one lane across bars."""
    lanes = defaultdict(list)
    result = []
    for ev in sorted(events, key=lambda e: (e.start_beat, e.pitch, e.note_id)):
        staff = staff_for_hand(ev.hand, ev.pitch) if grand_staff else 0
        selected = None
        for i, lane in enumerate(lanes[staff]):
            last = lane[-1]
            onset, duration = exact[ev.note_id][:2]
            last_onset, last_duration = exact[last.note_id][:2]
            same_chord = (onset == last_onset
                          and duration == last_duration
                          and ev.voice == last.voice
                          and ev.pitch != last.pitch)
            if same_chord or (last_onset + last_duration <= onset
                              and ev.voice == last.voice):
                selected = i
                break
        if selected is None:
            selected = len(lanes[staff])
            lanes[staff].append([])
        lanes[staff][selected].append(ev)
        result.append(copy_event(ev, voice=selected))
    return result


def _phrase_roles(voices, measure_length):
    """Score line hypotheses in four-bar contexts; roles may change over time.

Register is a weak prior. Stepwise motion, independent attacks, and sustained
presence favor a melodic line over a high, repeated accompaniment chord.
Confidence is deliberately uncalibrated and reported as such.
"""
    windows = defaultdict(dict)
    span = max(1.0, measure_length * 4)
    for key, events in voices.items():
        for ev in events:
            window = int(ev.start_beat // span)
            windows[window].setdefault(key, []).append(ev)
    result = {}
    previous = None
    for window, lines in sorted(windows.items()):
        scores = {}
        for key, notes in lines.items():
            attacks = defaultdict(list)
            for ev in notes:
                attacks[round(ev.start_beat, 3)].append(ev.pitch)
            pitches = [mean(ps) for _, ps in sorted(attacks.items())]
            motion = [abs(b - a) for a, b in zip(pitches, pitches[1:])]
            stepwise = mean(0 < leap <= 5 for leap in motion) if motion else 0.0
            repetition = mean(leap == 0 for leap in motion) if motion else 0.0
            independence = len(attacks) / len(notes)
            scores[key] = (mean(pitches) / 48 + 1.5 * stepwise
                           + independence - 0.6 * repetition
                           + (0.3 if key == previous else 0))
        melody = max(scores, key=scores.get)
        bass = min(lines, key=lambda key: mean(ev.pitch for ev in lines[key]))
        for key, notes in lines.items():
            role = "melody" if key == melody else "bass" if key == bass else "accompaniment"
            for ev in notes:
                result[ev.note_id] = (role, window)
        previous = melody
    return result


def hands_provided(events) -> bool:
    """True when every note already has a layout hand (including AMBIGUOUS)."""
    if not events:
        return False
    return all(
        ev.hand in _ASSIGNED_HANDS
        or (getattr(ev, "hand_locked", False) and ev.hand in (Hand.LEFT, Hand.RIGHT))
        for ev in events
    )


def voices_provided(events) -> bool:
    voices = {int(ev.voice) for ev in events}
    return len(voices) > 1 or any(int(ev.voice) != 0 for ev in events)


def _score_voices(events, separator):
    if type(separator) is VoiceSeparator:
        separator = VoiceSeparator(replace(separator.config, prefer_simple_chords=True,
                                           overlap_grace_beats=0.10))
    return separator.separate(events)


def assign_pipeline_layout(events, profile: ScoreProfile, hand_separator, voice_separator):
    out = list(events)
    if profile.grand_staff and not hands_provided(out):
        out = hand_separator.separate(out)
    if not voices_provided(out):
        out = _score_voices(out, voice_separator)
    return out


def resolve_layout(raw, profile: ScoreProfile):
    if not profile.grand_staff:
        cleared = [
            copy_event(ev, hand=Hand.UNKNOWN, hand_confidence=0.0, hand_locked=False)
            for ev in raw
        ]
        if voices_provided(raw):
            return cleared, "pipeline"
        return _score_voices(cleared, VoiceSeparator()), "inferred"
    if hands_provided(raw):
        return [copy_event(ev) for ev in raw], "pipeline"
    if voices_provided(raw):
        return HandSeparator().separate(raw), "mixed"
    return _score_voices(HandSeparator().separate(raw), VoiceSeparator()), "inferred"


def quantize_notation(events, meter, *, config, mode=None):
    from mir.quantizer import summarize_quantization

    ids = [e.note_id for e in events if e.note_id]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source note IDs")
    raw = []
    used = set(ids)
    for i, ev in enumerate(events):
        if (not isfinite(ev.start_beat) or not isfinite(ev.duration_beats)
                or ev.start_beat < 0 or ev.duration_beats <= 0):
            raise ValueError("Source note timing must be finite and positive")
        note_id = ev.note_id
        if not note_id:
            note_id = f"performance:{i}"
            while note_id in used:
                note_id += ":generated"
        used.add(note_id)
        raw.append(copy_event(ev, note_id=note_id))
    profile = score_profile(raw)
    interpreted, layout_source = resolve_layout(raw, profile)
    voices = defaultdict(list)
    for ev in interpreted:
        staff = staff_for_hand(ev.hand, ev.pitch) if profile.grand_staff else 0
        voices[(staff, ev.voice)].append(ev)

    roles = _phrase_roles(voices, meter.measure_quarter_length)
    out, exact = [], {}
    for key, voice in voices.items():
        groups = []
        for ev in sorted(voice, key=lambda e: (e.start_beat, e.pitch)):
            if (groups and abs(ev.start_beat - groups[-1][0].start_beat) <= 0.04
                    and all(ev.pitch != other.pitch for other in groups[-1])):
                groups[-1].append(ev)
            else:
                groups.append([ev])
        path = _search(groups, config.max_onset_move)
        for i, (group, (onset, family)) in enumerate(zip(groups, path)):
            nxt = path[i + 1][0] if i + 1 < len(path) else None
            neighbors = ([nxt - onset] if nxt is not None else [])
            if i:
                neighbors.append(onset - path[i - 1][0])
            if onset.denominator == 1 and any(d.denominator in (3, 6) for d in neighbors):
                family = "triplet"
            raw_next = min(e.start_beat for e in groups[i + 1]) if nxt is not None else None
            for ev in group:
                overlaps = raw_next is not None and ev.start_beat + ev.duration_beats > raw_next + 0.04
                duration = _duration(ev.duration_beats, onset, nxt, overlaps, family)
                exact[ev.note_id] = (onset, duration, family, f"{key[0]}:{key[1]}:{i}")
                role, phrase = roles[ev.note_id]
                out.append(copy_event(ev, start_beat=float(onset), duration_beats=float(duration),
                                      role=role, phrase_id=phrase))
    out = _stable_lanes(out, exact, profile.grand_staff)
    raw_by_id = {e.note_id: e for e in raw}
    decisions, notes = [], []
    for ev in out:
        source = raw_by_id[ev.note_id]
        onset, duration, family, group_id = exact[ev.note_id]
        notes.append(ScoreNote(ev.note_id, onset, duration, ev.voice,
                               staff_for_hand(ev.hand, ev.pitch) if profile.grand_staff else 0,
                               ev.role, family, group_id))
        decisions.append({
            "note_id": ev.note_id, "raw_start": source.start_beat,
            "source_track_id": ev.source_track_id, "source_program": ev.source_program,
            "raw_duration": source.duration_beats, "quantized_start": ev.start_beat,
            "quantized_duration": ev.duration_beats, "score_onset": str(onset),
            "score_duration": str(duration), "voice": ev.voice, "hand": ev.hand.value,
            "role": ev.role, "role_confidence": 0.4, "rhythm_family": family,
            "phrase_id": ev.phrase_id, "hand_confidence": ev.hand_confidence,
            "voice_confidence": ev.voice_confidence,
            "group_id": group_id, "reason": "bounded_voice_search",
        })
    summary = summarize_quantization(raw, out, decisions)
    summary.update(engine="performance", voice_count=len({(n.staff, n.voice) for n in notes}),
                   role_method="contextual_line_hypothesis", role_confidence=0.4,
                   timing_representation="rational", source_notes=len(raw),
                   layout_source=layout_source,
                   score_profile=profile.to_dict())
    return out, decisions, PerformanceReport(summary, tuple(notes), decisions)
