"""Bounded performance-to-score inference with immutable source provenance.

Tempo and meter remain upstream hypotheses. Rhythm search consumes the
pipeline's hand/voice graph when it is already assigned. Separators run
only for unlabeled piano (or unlabeled voices on a single staff). Exact
score positions are retained separately from the float-based compatibility
events.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
from fractions import Fraction
from math import isfinite
from statistics import mean

from mir.hand_separator import HandSeparator
from mir.layout import (
    LayoutAuthority,
    LayoutResult,
    classify_hand_authority,
    hands_complete,
    voices_complete,
)
from mir.models import staff_for_hand
from mir.score_profile import ScoreProfile, collapse_for_solo_notation, score_profile
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
    # An already representable attack is stronger evidence than a preference
    # for a simpler rhythm. In particular, preserve 64ths and offbeat triplets.
    for denominator, family in ((1, "binary"), (2, "binary"), (4, "binary"),
                                (8, "binary"), (16, "binary"),
                                (3, "triplet"), (6, "triplet"),
                                (12, "triplet"), (24, "triplet"), (48, "triplet")):
        exact = Fraction(round(raw * denominator), denominator)
        if abs(float(exact) - raw) <= min(1e-7, max_move):
            return [(exact, family, 0.0)]
    candidates = {}
    for denominator, family, complexity in (
        (1, "binary", 0.0), (2, "binary", 0.008),
        (4, "binary", 0.016), (8, "binary", 0.035),
        (3, "triplet", 0.035), (6, "triplet", 0.05),
        (16, "binary", 0.08),
        (12, "triplet", 0.09), (24, "triplet", 0.12), (48, "triplet", 0.16),
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


def _written_overlap(raw, onset, next_onset, overlaps):
    """Pedal/room tails overlap the next attack; multi-bar holds do not."""
    if not overlaps or next_onset is None:
        return overlaps
    gap = float(next_onset - onset)
    if gap <= 0.12 or raw <= gap * 1.25:
        return overlaps
    # Repeated accompaniment under sustain pedal is a bit longer than the
    # pulse. A true held note spanning several attacks is many times longer.
    if 0.20 <= gap <= 2.05 and raw < gap * 4.0:
        return False
    return overlaps


def _fragment_count(onset: Fraction, duration: Fraction, beat_length=Fraction(1)) -> int:
    """Count engraved pieces after the same barline splitting used by export."""
    from notation_engine.exact_plan import _pieces

    return sum(1 for _ in _pieces(onset, duration, beat_length))


def _duration_spelling_cost(raw, onset, duration, family):
    """Prefer spellings that stay simple after barline splitting."""
    beat_length = Fraction(1)
    fragments = _fragment_count(onset, duration, beat_length)
    denom = duration.denominator
    numerator = duration.numerator
    while numerator % 2 == 0:
        numerator //= 2
    odd = numerator not in (1, 3)
    err = abs(float(duration) - raw)
    # Do not invent a long written overrun or truncate a hold just to
    # avoid a barline tie.
    stretch = max(0.0, float(duration) - raw - 0.12)
    shrink = max(0.0, raw - float(duration) - 0.12)
    tiny_tail = 0
    if fragments >= 2 and denom >= 16:
        tiny_tail = 1
    if family != "triplet" and denom >= 32:
        tiny_tail += 1
    # Isolated fine-grid tails without tuplet evidence.
    if family != "triplet" and denom >= 16 and err < 0.08 and fragments > 1:
        tiny_tail += 2
    mistimed = stretch > 0.25 or shrink > 0.25
    return (mistimed, fragments, tiny_tail, odd, err, denom, duration)


def _duration(raw, onset, next_onset, overlaps, family, *, preserve=False):
    unit = Fraction(1, 48) if family == "triplet" else Fraction(1, 16)
    onset = Fraction(onset) if not isinstance(onset, Fraction) else onset
    named = {Fraction(n, d) for d in (1, 2, 4, 8, 16)
             for n in (1, 2, 3, 4, 6, 8, 12, 16)}
    if family == "triplet":
        named.update(Fraction(n, d) for d in (6, 12, 24, 48) for n in (1, 2, 4, 8, 16))
    # Long sustains remain possible and will be split into barline ties.
    named.add(max(unit, round(raw / float(unit)) * unit))
    # Metrical releases near integer/half/dotted boundaries.
    for boundary in (1, 2, 3, 4, 5, 6, 7, 8, Fraction(3, 2), Fraction(1, 2), Fraction(3, 4)):
        if abs(raw - float(boundary)) <= 0.35:
            named.add(Fraction(boundary))
    if preserve:
        exact = min(named, key=lambda d: abs(float(d) - raw))
        if abs(float(exact) - raw) < 1e-7:
            return exact
    written_overlap = overlaps if preserve else _written_overlap(raw, onset, next_onset, overlaps)
    if next_onset is not None and not written_overlap:
        cap = Fraction(next_onset) - onset if not isinstance(next_onset, Fraction) else next_onset - onset
        if not isinstance(cap, Fraction):
            cap = Fraction(cap).limit_denominator(48)
        named = {d for d in named if d <= cap + Fraction(1, 10**9)}
        if cap > 0:
            named.add(cap)
            # Prefer the same-line attack as a written release when it is a
            # simple value near the performed decay.
            if abs(float(cap) - raw) <= max(0.95, raw * 0.55):
                named.add(cap)
    if not named:
        named = {max(unit, round(raw / float(unit)) * unit)}
    # Score the whole written ending, not only acoustic proximity.
    return min(named, key=lambda d: _duration_spelling_cost(raw, onset, d, family))


def _score_voices(events, separator):
    if type(separator) is VoiceSeparator:
        cap = min(2, int(separator.config.max_voices_per_hand or 2))
        separator = VoiceSeparator(replace(
            separator.config,
            prefer_simple_chords=True,
            # Keep a tight grace; pedal tails are shortened only for the
            # voice-search copy below so genuine overlaps stay independent.
            overlap_grace_beats=0.10,
            max_voices_per_hand=cap,
        ))
    search = _voice_search_events(events)
    voiced = separator.separate(search)
    by_id = {ev.note_id: ev.voice for ev in voiced}
    restored = [
        copy_event(ev, voice=by_id.get(ev.note_id, ev.voice))
        for ev in events
    ]
    return _mark_voices_assigned(restored)


def _voice_search_events(events):
    """Cap pedal-like tails for voice search without mutating performed times.

    Repeated same-hand attacks under sustain look overlapping because the
    acoustic release outlasts the pulse. Cap those tails at the next
    same-line attack so they stay on one written line. Genuine independent
    streams keep their performed endings and can still open a second voice.
    """
    by_hand = defaultdict(list)
    for ev in events:
        by_hand[ev.hand].append(ev)
    capped = {}
    for group in by_hand.values():
        ordered = sorted(group, key=lambda e: (e.start_beat, e.pitch, e.note_id))
        for i, ev in enumerate(ordered):
            next_onset = None
            for later in ordered[i + 1:]:
                if later.start_beat <= ev.start_beat + 1e-9:
                    continue
                # Same musical line: nearby pitch continuation, not the
                # interleaved independent stream an octave away.
                if abs(later.pitch - ev.pitch) <= 9:
                    next_onset = later.start_beat
                    break
            if next_onset is None:
                capped[ev.note_id] = ev
                continue
            raw = float(ev.duration_beats)
            gap = float(next_onset - ev.start_beat)
            # Pedal/room tail under a repeated figure: longer than the pulse
            # but not a multi-attack held note.
            if 0.20 <= gap <= 2.05 and gap * 1.25 < raw < gap * 4.0:
                capped[ev.note_id] = copy_event(ev, duration_beats=gap)
            else:
                capped[ev.note_id] = ev
    return [capped.get(ev.note_id, ev) for ev in events]


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
    """Backward-compatible alias for an already-complete hand layout."""
    return hands_complete(events)


def voices_provided(events) -> bool:
    """Backward-compatible alias; includes an explicit single voice 0."""
    return voices_complete(events)


def _mark_voices_assigned(events):
    return [copy_event(ev, voice_assigned=True) for ev in events]


def assign_pipeline_layout(events, profile: ScoreProfile, hand_separator, voice_separator):
    """Assign hands/voices once on the understanding path.

    Returns a LayoutResult so export can consume authority without re-inferring.
    Piano gets the configured hand separator only when hands are still
    unlabeled. Voices are inferred after that, including the valid single
    voice-0 case. Non-piano sources never receive piano hand labels.
    """
    out = list(events)
    inferred_hands = False
    if profile.grand_staff and not hands_complete(out):
        out = hand_separator.separate(out)
        inferred_hands = True
    voice_was_complete = voices_complete(out)
    if not voice_was_complete:
        out = _score_voices(out, voice_separator)
    elif not all(getattr(ev, "voice_assigned", False) for ev in out):
        out = _mark_voices_assigned(out)

    if not profile.grand_staff:
        authority = LayoutAuthority.PROVIDER if voice_was_complete else LayoutAuthority.INFERRED
    elif inferred_hands and voice_was_complete:
        authority = LayoutAuthority.MIXED
    elif inferred_hands:
        authority = LayoutAuthority.INFERRED
    else:
        authority = classify_hand_authority(out)
        if authority is LayoutAuthority.NONE:
            authority = LayoutAuthority.PROVIDER
    return LayoutResult(
        events=out,
        authority=authority,
        voice_complete=True,
        hand_complete=hands_complete(out) if profile.grand_staff else True,
    )


def resolve_layout(raw, profile: ScoreProfile):
    """Keep pipeline/MIDI layout; infer only when the events are unlabeled."""
    if not profile.grand_staff:
        cleared = [
            copy_event(ev, hand=Hand.UNKNOWN, hand_confidence=0.0, hand_locked=False)
            for ev in raw
        ]
        if voices_complete(raw):
            events = [
                copy_event(
                    cleared[i],
                    voice=raw[i].voice,
                    voice_assigned=True,
                )
                for i in range(len(raw))
            ]
            result = LayoutResult(events, LayoutAuthority.PROVIDER, True, True)
            return result.events, result.layout_source
        events = _score_voices(cleared, VoiceSeparator())
        result = LayoutResult(events, LayoutAuthority.INFERRED, True, True)
        return result.events, result.layout_source

    if hands_complete(raw):
        authority = classify_hand_authority(raw)
        events = [copy_event(ev) for ev in raw]
        # Hands already supplied by pipeline/MIDI: keep their voice numbers,
        # including an intentional single voice 0. Do not re-separate.
        if not all(getattr(ev, "voice_assigned", False) for ev in events):
            events = _mark_voices_assigned(events)
        if authority is LayoutAuthority.NONE:
            authority = LayoutAuthority.PROVIDER
        result = LayoutResult(events, authority, True, True)
        return result.events, result.layout_source

    if voices_complete(raw):
        hands = HandSeparator().separate(raw)
        events = [
            copy_event(out, voice=src.voice, voice_assigned=True)
            for src, out in zip(raw, hands)
        ]
        result = LayoutResult(events, LayoutAuthority.MIXED, True, True)
        return result.events, result.layout_source

    events = _score_voices(HandSeparator().separate(raw), VoiceSeparator())
    result = LayoutResult(events, LayoutAuthority.INFERRED, True, True)
    return result.events, result.layout_source


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
    # Downbeat phase belongs to score coordinates, never to the source MIDI.
    downbeats = [float(beat) for beat in meter.evidence.get("downbeat_beats", [])
                 if isfinite(float(beat)) and float(beat) >= 0]
    offset = (-min(downbeats)) % meter.measure_quarter_length if downbeats else 0.0
    if abs(offset - meter.measure_quarter_length) < 1e-7:
        offset = 0.0
    score_input = [copy_event(ev, start_beat=ev.start_beat + offset) for ev in raw]
    score_input, profile, collapse_warning = collapse_for_solo_notation(score_input)
    interpreted, layout_source = resolve_layout(score_input, profile)
    voices = defaultdict(list)
    for ev in interpreted:
        staff = staff_for_hand(ev.hand, ev.pitch) if profile.grand_staff else 0
        voices[(staff, ev.voice)].append(ev)

    roles = _phrase_roles(voices, meter.measure_quarter_length)
    out, exact = [], {}
    for key, voice in voices.items():
        groups = []
        for ev in sorted(voice, key=lambda e: (e.start_beat, e.pitch)):
            chord_tolerance = 1e-7 if ev.source_backend == "midi" else 0.04
            if (groups and abs(ev.start_beat - groups[-1][0].start_beat) <= chord_tolerance
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
            if onset.denominator == 1 and any(d.denominator % 3 == 0 for d in neighbors):
                family = "triplet"
            raw_next = min(e.start_beat for e in groups[i + 1]) if nxt is not None else None
            for ev in group:
                overlaps = raw_next is not None and ev.start_beat + ev.duration_beats > raw_next + 0.04
                duration = _duration(ev.duration_beats, onset, nxt, overlaps, family,
                                     preserve=ev.source_backend == "midi")
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
            "source_track_id": source.source_track_id, "source_program": source.source_program,
            "raw_duration": source.duration_beats, "quantized_start": ev.start_beat,
            "quantized_duration": ev.duration_beats, "score_onset": str(onset),
            "score_duration": str(duration),
            "performed_duration": source.duration_beats,
            "written_duration": float(duration),
            "voice": ev.voice, "hand": ev.hand.value,
            "role": ev.role, "role_confidence": 0.4, "rhythm_family": family,
            "phrase_id": ev.phrase_id, "hand_confidence": ev.hand_confidence,
            "voice_confidence": ev.voice_confidence,
            "group_id": group_id, "reason": "bounded_voice_search",
            "score_beat_offset": offset,
            "onset_error_beats": ev.start_beat - offset - source.start_beat,
        })
    summary = summarize_quantization(raw, out, decisions)
    if collapse_warning:
        summary["solo_collapse_warning"] = collapse_warning
    summary.update(engine="performance", voice_count=len({(n.staff, n.voice) for n in notes}),
                   role_method="contextual_line_hypothesis", role_confidence=0.4,
                   timing_representation="rational", source_notes=len(raw),
                   layout_source=layout_source,
                   score_beat_offset=offset,
                   beat_origin_source="detected_downbeat" if downbeats else "file_origin",
                   max_onset_error_beats=max((abs(d["onset_error_beats"]) for d in decisions), default=0),
                   score_profile=profile.to_dict())
    return out, decisions, PerformanceReport(summary, tuple(notes), decisions)
