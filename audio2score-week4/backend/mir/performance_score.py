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
    stamp_authority,
    stamped_authority,
    voices_complete,
)
from mir.models import staff_for_hand
from mir.notation_settings import (
    DisplayGrid,
    Interpretation,
    NotationSettings,
    OverlapHandling,
    TripletPolicy,
    parse_notation_settings,
)
from mir.pipeline_config import require_production_quantization_mode
from mir.score_profile import ScoreProfile, collapse_for_solo_notation, score_profile
from mir.types import Hand, copy_event
from mir.voice_separator import VoiceSeparator

_ASSIGNED_HANDS = {Hand.LEFT, Hand.RIGHT, Hand.AMBIGUOUS}

_GRID_BINARY_DENOMS = {
    DisplayGrid.EIGHTH: 2,
    DisplayGrid.SIXTEENTH: 4,
    DisplayGrid.THIRTY_SECOND: 8,
}

_ONSET_EXACT = (
    (1, "binary"), (2, "binary"), (4, "binary"),
    (8, "binary"), (16, "binary"),
    (3, "triplet"), (6, "triplet"),
    (12, "triplet"), (24, "triplet"), (48, "triplet"),
)
_ONSET_SEARCH = (
    (1, "binary", 0.0), (2, "binary", 0.008),
    (4, "binary", 0.016), (8, "binary", 0.035),
    (3, "triplet", 0.035), (6, "triplet", 0.05),
    (16, "binary", 0.08),
    (12, "triplet", 0.09), (24, "triplet", 0.12), (48, "triplet", 0.16),
)


def _settings(settings) -> NotationSettings:
    return parse_notation_settings(settings)


def _local_bpm(event, tempo_map) -> float:
    if tempo_map is not None:
        moment = getattr(event, "start_time_sec", None)
        if moment is None:
            moment = getattr(event, "end_time_sec", None)
        if moment is not None:
            return float(tempo_map.bpm_at(moment) or 120.0)
        bpm = getattr(tempo_map, "bpm_at", None)
        if callable(bpm):
            return float(tempo_map.bpm_at(0.0) or 120.0)
        return 120.0
    start_sec = getattr(event, "start_time_sec", None)
    start_beat = float(getattr(event, "start_beat", 0.0) or 0.0)
    if start_sec is not None and start_beat > 1e-9:
        return 60.0 * float(start_sec) / start_beat
    return 120.0


def beats_to_ms(beats, bpm) -> float:
    return float(beats) * (60000.0 / max(float(bpm), 1e-6))


def pedal_spans(pedal_events, *, track_id=None) -> tuple[tuple[float, float], ...]:
    """Build sustain spans from CC64.

    2-tuples apply globally (legacy ingest). 3-tuples ``(time, value, track)``
    belong to one source stream; ``track_id`` then ignores other tracks.
    """
    spans = []
    down_at = None
    filtered = []
    for item in pedal_events or ():
        time_sec = float(item[0])
        value = int(item[1])
        item_track = item[2] if len(item) > 2 else None
        if track_id is not None and item_track is not None and str(item_track) != str(track_id):
            continue
        filtered.append((time_sec, value))
    for time_sec, value in sorted(filtered, key=lambda row: row[0]):
        on = value >= 64
        if on and down_at is None:
            down_at = time_sec
        elif not on and down_at is not None:
            spans.append((down_at, time_sec))
            down_at = None
    if down_at is not None:
        spans.append((down_at, float("inf")))
    return tuple(spans)


def pedal_down_at(spans, time_sec) -> bool:
    if time_sec is None or not spans:
        return False
    moment = float(time_sec)
    return any(start <= moment < end for start, end in spans)


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
    musical_voice: int | None = None
    voice_provenance: str = ""


@dataclass
class PerformanceReport:
    summary: dict
    notes: tuple[ScoreNote, ...]
    decisions: list[dict]


SCORE_FRACTION_LIMIT = 192
SCORE_FRACTION_TOLERANCE = 1e-9


def _already_notated_fraction(value, *, positive: bool = False) -> Fraction | None:
    """Recover a binary or tuplet spelling already present in ``value``.

    ``snap_writable_length`` rounds 1/3 onto the 64th grid (0.3125). Already
    notated tuplets must not take that path.
    """
    frac = Fraction(value).limit_denominator(SCORE_FRACTION_LIMIT)
    if abs(float(frac) - float(value)) > SCORE_FRACTION_TOLERANCE:
        return None
    if positive and frac <= 0:
        return None
    if frac < 0:
        return None
    den = frac.denominator
    while den % 2 == 0:
        den //= 2
    if den not in (1, 3):
        return None
    return frac


def as_score_fraction(value, *, positive: bool = False, previous: Fraction | None = None, locked: bool = False) -> Fraction:
    """Convert a score-beat value without inventing a simpler spelling.

    Locked (user-edited) values stay exact so the planner can reject an
    unspellable duration instead of silently rounding. Unlocked values, such
    as performance-mapped editor floats, use the 64th writable grid already
    used by the quantizer — unless the float is already a notated binary or
    tuplet spelling.
    """
    if previous is not None and abs(float(previous) - float(value)) <= SCORE_FRACTION_TOLERANCE:
        return Fraction(previous)
    if locked:
        frac = Fraction(value).limit_denominator(SCORE_FRACTION_LIMIT)
        if positive and frac <= 0:
            raise ValueError(f"Edited duration {value} is not a positive writable length")
        if frac < 0:
            raise ValueError(f"Edited onset {value} is negative")
        return frac
    notated = _already_notated_fraction(value, positive=positive)
    if notated is not None:
        return notated
    from mir.quantizer import SMALLEST_WRITABLE, snap_writable_length

    if positive:
        snapped = snap_writable_length(value, allow_empty=False)
        return Fraction(str(snapped)).limit_denominator(64)
    if abs(float(value)) < SMALLEST_WRITABLE / 2:
        return Fraction(0)
    snapped = snap_writable_length(max(0.0, float(value)), allow_empty=True)
    return Fraction(str(snapped)).limit_denominator(64)


def report_from_events(events, *, previous=None, summary=None) -> PerformanceReport:
    """Build a PerformanceReport from already-quantized or explicitly edited events.

    Reuses previous rational onsets/durations/lanes when the event still
    matches, so a velocity-only edit cannot change engraving structure.
    Locked timing always comes from the event.
    """
    summary = dict(summary or (getattr(previous, "summary", None) or {}) or {})
    profile = summary.get("score_profile")
    if not profile:
        profile = score_profile(events).to_dict() if events else {
            "grand_staff": True,
            "program": 0,
            "clef": "treble",
            "evidence": "empty_score",
        }
        summary["score_profile"] = profile
    grand = bool(profile.get("grand_staff", True))
    prev_notes = {n.source_id: n for n in (getattr(previous, "notes", None) or ())}
    notes = []
    for index, ev in enumerate(events):
        sid = ev.note_id or f"event:{index}"
        staff = staff_for_hand(ev.hand, ev.pitch) if grand else 0
        voice = int(ev.voice or 0)
        locked = bool(getattr(ev, "score_timing_locked", False))
        old = prev_notes.get(sid)
        if (
            old is not None
            and not locked
            and abs(float(old.onset) - float(ev.start_beat)) <= SCORE_FRACTION_TOLERANCE
            and abs(float(old.duration) - float(ev.duration_beats)) <= SCORE_FRACTION_TOLERANCE
            and int(old.voice) == voice
            and int(old.staff) == staff
        ):
            notes.append(
                ScoreNote(
                    sid,
                    old.onset,
                    old.duration,
                    old.voice,
                    old.staff,
                    old.role,
                    old.rhythm_family,
                    old.group_id,
                    musical_voice=ev.musical_voice if ev.musical_voice is not None else old.musical_voice,
                    voice_provenance=ev.voice_provenance or old.voice_provenance,
                )
            )
            continue
        onset = as_score_fraction(
            ev.start_beat,
            previous=None if locked or old is None else old.onset,
            locked=locked,
        )
        duration = as_score_fraction(
            ev.duration_beats,
            positive=True,
            previous=None if locked or old is None else old.duration,
            locked=locked,
        )
        notes.append(
            ScoreNote(
                sid,
                onset,
                duration,
                voice,
                staff,
                ev.role or (old.role if old is not None else ""),
                old.rhythm_family if old is not None and not locked else "binary",
                old.group_id if old is not None and not locked else f"{staff}:{voice}:{index}",
                musical_voice=ev.musical_voice if ev.musical_voice is not None else (
                    old.musical_voice if old is not None else None
                ),
                voice_provenance=ev.voice_provenance or (
                    old.voice_provenance if old is not None else ""
                ),
            )
        )
    return PerformanceReport(
        summary,
        _serial_score_notes(tuple(notes)),
        list(getattr(previous, "decisions", None) or []),
    )


def _serial_score_notes(notes: tuple[ScoreNote, ...]) -> tuple[ScoreNote, ...]:
    """Give overlapping non-chord attacks distinct printed lanes.

    Same onset and duration stay a chord. Explicit user voices that already
    differ are left alone. Same-voice collisions with different spans get a
    new printed lane so exact-plan export does not raise or merge attacks.
    """
    from collections import defaultdict

    by_staff: dict[int, list[ScoreNote]] = defaultdict(list)
    for note in notes:
        by_staff[int(note.staff)].append(note)
    out: list[ScoreNote] = []
    for staff, rows in by_staff.items():
        occupied: dict[int, list[tuple[Fraction, Fraction, str]]] = defaultdict(list)
        next_voice = max((int(row.voice) for row in rows), default=-1) + 1
        for note in sorted(rows, key=lambda row: (row.onset, row.duration, row.source_id)):
            voice = int(note.voice)
            end = note.onset + note.duration
            conflict = False
            for other_on, other_end, other_id in occupied[voice]:
                if other_id == note.source_id:
                    continue
                same_span = other_on == note.onset and other_end == end
                overlaps = note.onset < other_end and other_on < end
                if overlaps and not same_span:
                    conflict = True
                    break
            if conflict:
                voice = next_voice
                next_voice += 1
            occupied[voice].append((note.onset, end, note.source_id))
            if voice != note.voice:
                note = ScoreNote(
                    note.source_id,
                    note.onset,
                    note.duration,
                    voice,
                    note.staff,
                    note.role,
                    note.rhythm_family,
                    note.group_id,
                    musical_voice=note.musical_voice,
                    voice_provenance=note.voice_provenance,
                )
            out.append(note)
    return tuple(out)


def _onset_vocab(settings: NotationSettings, *, allow_finer=False):
    settings = _settings(settings)
    exact = list(_ONSET_EXACT)
    search = list(_ONSET_SEARCH)
    if not (settings.uses_current_vocabulary() or allow_finer):
        max_binary = _GRID_BINARY_DENOMS.get(settings.display_grid)
        if max_binary is not None:
            exact = [
                (denom, family) for denom, family in exact
                if family != "binary" or denom <= max_binary
            ]
            search = [
                row for row in search
                if row[1] != "binary" or row[0] <= max_binary
            ]
    if settings.triplet_policy == TripletPolicy.DISABLED:
        exact = [(denom, family) for denom, family in exact if family != "triplet"]
        search = [row for row in search if row[1] != "triplet"]
    elif settings.triplet_policy == TripletPolicy.ENABLED:
        search = [
            (denom, family, cost * (0.85 if family == "triplet" else 1.0))
            for denom, family, cost in search
        ]
    if not exact:
        exact = [
            (denom, family) for denom, family in _ONSET_EXACT
            if family != "triplet" or settings.triplet_policy != TripletPolicy.DISABLED
        ]
    if not search:
        search = [
            row for row in _ONSET_SEARCH
            if row[1] != "triplet" or settings.triplet_policy != TripletPolicy.DISABLED
        ]
    return exact, search


def _exact_onset_hit(raw, max_move, exact_vocab):
    for denominator, family in exact_vocab:
        exact = Fraction(round(raw * denominator), denominator)
        if abs(float(exact) - raw) <= min(1e-7, max_move):
            return exact, family, 0.0
    return None


def _readable_may_simplify_exact(onset: Fraction, family: str) -> bool:
    """Readable may consider coarser alternatives for fine binary grids.

    Exact tuplets and coarse binary attacks (quarters through sixteenths) stay
    exclusive so deliberate syncopation and tuplet spelling are preserved.
    """
    if family != "binary":
        return False
    return onset.denominator > 4


def _onset_candidates(raw, max_move, settings=None, exceptions=None):
    settings = _settings(settings)
    # An already representable attack is strong evidence. Literal keeps it
    # exclusive. Readable still seeds it at cost 0, but also considers simpler
    # binary alternatives for fine grids so accompaniment can share a beat.
    exact_vocab, search_vocab = _onset_vocab(settings)
    exact_hit = _exact_onset_hit(raw, max_move, exact_vocab)
    # Exact values outside the selected grid still win: they are distinct attacks.
    # Triplet policy is still honored; a required tuplet is a recorded exception.
    if exact_hit is None and not settings.uses_current_vocabulary():
        fallback_exact = _ONSET_EXACT
        if settings.triplet_policy == TripletPolicy.DISABLED:
            fallback_exact = [(d, f) for d, f in _ONSET_EXACT if f != "triplet"]
        exact_hit = _exact_onset_hit(raw, max_move, fallback_exact)
    candidates = {}
    literal = settings.interpretation == Interpretation.LITERAL
    if exact_hit is not None:
        onset, family, cost = exact_hit
        if literal or not _readable_may_simplify_exact(onset, family):
            return [(onset, family, cost)]
        candidates[(onset, family)] = cost

    def _collect(vocab):
        for denominator, family, complexity in vocab:
            center = round(raw * denominator)
            for tick in range(center - 1, center + 2):
                onset = Fraction(tick, denominator)
                error = abs(float(onset) - raw)
                if onset < 0 or error > max_move:
                    continue
                # Performance jitter is not evidence for a 32nd/64th or a tuplet.
                # Keep the full vocabulary for genuinely distinct fast attacks;
                # prefer simpler values inside a small, bounded timing tolerance.
                tolerance = 0.0 if literal else (
                    0.065 if family == "binary" and denominator <= 4 else 0.0
                )
                cost = max(0.0, error - tolerance) * 3 + complexity
                # Near a beat, Readable prefers landing on that beat over a
                # barely closer 32nd when both stay inside the move bound.
                if (
                    not literal
                    and family == "binary"
                    and denominator <= 2
                    and error <= 0.12
                ):
                    cost -= 0.02
                key = (onset, family)
                if key not in candidates or cost < candidates[key]:
                    candidates[key] = cost

    _collect(search_vocab)
    if not candidates and settings.triplet_policy == TripletPolicy.DISABLED:
        _collect([row for row in _ONSET_SEARCH if row[1] == "triplet"])
        if candidates and exceptions is not None:
            exceptions.append(
                {
                    "kind": "triplet_policy",
                    "policy": "disabled",
                    "onset": float(raw),
                    "reason": "A local tuplet was needed to keep this attack on the page.",
                    "user_message": "A local tuplet was needed to keep this attack on the page.",
                }
            )
    if not candidates:
        _collect(_ONSET_SEARCH)
    if not candidates:
        raise ValueError(f"No readable onset within timing bound at {raw}")
    return [(onset, family, cost) for (onset, family), cost in candidates.items()]


def _search(groups, max_move, beam_width=24, settings=None, measure_length=None, exceptions=None):
    # State includes the previous interval so recurring figures favor the same
    # interpretation. Strict ordering is a constraint, never a repair pass.
    settings = _settings(settings)
    path = _search_beam(
        groups, max_move, beam_width, settings,
        measure_length=measure_length, exceptions=exceptions,
    )
    if not settings.uses_improved_readable() or len(path) < 3:
        return path
    families = [family for onset, family in path if onset.denominator != 1]
    if not families:
        return path
    dominant = max(set(families), key=families.count)
    if families.count(dominant) < max(2, (len(families) + 1) // 2):
        return path
    preferred = _settings(settings.to_dict())
    if dominant == "triplet" and preferred.triplet_policy == TripletPolicy.AUTO:
        preferred = preferred.replace(triplet_policy=TripletPolicy.ENABLED)
    elif dominant == "binary" and preferred.triplet_policy == TripletPolicy.AUTO:
        preferred = preferred.replace(triplet_policy=TripletPolicy.DISABLED)
    try:
        alt = _search_beam(
            groups, max_move, beam_width, preferred,
            measure_length=measure_length, exceptions=exceptions,
        )
    except ValueError:
        return path
    # Keep the unified spelling only when attack order and the bound still hold.
    if len(alt) != len(path):
        return path
    return alt


def _search_beam(groups, max_move, beam_width, settings, measure_length=None, exceptions=None):
    beam = [(0.0, (), None)]
    for group in groups:
        raw = mean(e.start_beat for e in group)
        local = settings
        if measure_length:
            bar_number = int(Fraction(str(raw)) / Fraction(measure_length)) + 1 if measure_length else 1
            local = settings.resolved_for_measure(max(1, bar_number))
        next_beam = []
        for cost, path, last_interval in beam:
            for onset, family, local_cost in _onset_candidates(
                raw, max_move, local, exceptions=exceptions
            ):
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


def _written_overlap(raw, onset, next_onset, overlaps, *, release_reason=None, settings=None):
    """Decide whether the written ending may overlap the next attack.

    An explicit release hypothesis wins over the acoustic ratio heuristic so an
    independent hold is not silently shortened to the next same-line attack.
    """
    settings = _settings(settings)
    if settings.overlap_handling == OverlapHandling.PRESERVE:
        return bool(overlaps)
    if release_reason in {"pedal_tail", "reattack"}:
        return False
    if release_reason in {
        "no_line",
        "independent_hold",
        "overlapping_repeat",
        "multi_attack_hold",
    }:
        # Keep the hold; resolve overlap by lane/voice allocation, not truncation.
        return True
    if release_reason in {"performed_release", "phrase_end"}:
        return bool(overlaps)
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


def _stream_key(ev) -> tuple[str, object]:
    """Source stream plus hand: another track's notes are not release targets."""
    return (str(getattr(ev, "source_track_id", None) or ""), ev.hand)


def _release_decisions(events, *, settings=None, pedal=None):
    """Map note_id -> (release_target_id_or_None, reason, pedal_source)."""
    by_stream = defaultdict(list)
    for ev in events:
        by_stream[_stream_key(ev)].append(ev)
    decisions = {}
    for stream_key, group in by_stream.items():
        track_id = stream_key[0] or None
        spans = pedal_spans(pedal, track_id=track_id)
        ordered = sorted(group, key=lambda e: (e.start_beat, e.pitch, e.note_id))
        for ev in ordered:
            decisions[ev.note_id] = _release_hypothesis(
                ev, ordered, settings=settings, pedal=spans
            )
    return decisions


def _fragment_count(onset: Fraction, duration: Fraction, beat_length=Fraction(1)) -> int:
    """Count engraved pieces after the same barline splitting used by export."""
    return _engraved_release_stats(
        onset, duration, measure_length=Fraction(4), beat_length=beat_length
    )[0]


def _engraved_release_stats(
    onset: Fraction,
    duration: Fraction,
    *,
    measure_length: Fraction,
    beat_length: Fraction,
) -> tuple[int, int, int]:
    """Return (fragments, tie_joins, tiny_pieces) after real barline splitting."""
    from notation_engine.exact_plan import _pieces

    if duration <= 0:
        return 0, 0, 0
    onset = Fraction(onset)
    duration = Fraction(duration)
    measure_length = Fraction(measure_length)
    beat_length = Fraction(beat_length)
    end = onset + duration
    fragments = 0
    ties = 0
    tiny = 0
    pos = onset
    first_segment = True
    while pos < end - Fraction(1, 10**9):
        bar_index = int(pos / measure_length) if measure_length > 0 else 0
        bar_start = bar_index * measure_length
        bar_end = bar_start + measure_length
        seg_end = min(end, bar_end)
        local_start = pos - bar_start
        local_dur = seg_end - pos
        pieces = list(_pieces(local_start, local_dur, beat_length))
        if not first_segment:
            ties += 1
        if pieces:
            ties += max(0, len(pieces) - 1)
            fragments += len(pieces)
            for _offset, length in pieces:
                if length <= Fraction(1, 32):
                    tiny += 1
        first_segment = False
        pos = seg_end
    return fragments, ties, tiny


def _beat_length_for_meter(meter) -> Fraction:
    denominator = int(getattr(meter, "denominator", 4) or 4)
    numerator = int(getattr(meter, "numerator", 4) or 4)
    if denominator == 8 and numerator > 3 and numerator % 3 == 0:
        return Fraction(3, 2)
    return Fraction(4, denominator)


def _duration_spelling_cost(
    raw,
    onset,
    duration,
    family,
    *,
    measure_length=Fraction(4),
    beat_length=Fraction(1),
):
    """Prefer spellings that stay simple after meter-aware barline splitting."""
    fragments, ties, tiny_pieces = _engraved_release_stats(
        Fraction(onset),
        Fraction(duration),
        measure_length=Fraction(measure_length),
        beat_length=Fraction(beat_length),
    )
    denom = duration.denominator
    numerator = duration.numerator
    while numerator % 2 == 0:
        numerator //= 2
    odd = numerator not in (1, 3)
    err = abs(float(duration) - raw)
    stretch = max(0.0, float(duration) - raw - 0.12)
    shrink = max(0.0, raw - float(duration) - 0.12)
    tiny_tail = tiny_pieces
    if family != "triplet" and denom >= 32:
        tiny_tail += 1
    if family != "triplet" and denom >= 16 and err < 0.08 and fragments > 1:
        tiny_tail += 2
    mistimed = stretch > 0.25 or shrink > 0.25
    return (mistimed, fragments, ties, tiny_tail, odd, err, denom, duration)


def _dot_count(value: Fraction) -> int:
    q = Fraction(value)
    n, d = q.numerator, q.denominator
    while d % 2 == 0:
        d //= 2
    if d != 1:
        return 0
    while n % 2 == 0:
        n //= 2
    if n <= 1:
        return 0
    if (n + 1) & n == 0:
        return (n + 1).bit_length() - 2
    return 0


def _triplet_local_pulse(interval):
    """Preceding interval that can stand in for a missing next triplet onset.

    Already-notated tuplets keep their exact fractions elsewhere. This only
    names a coherent performed pulse (denominator divisible by 3) so a group
    ending can use the same leftover-gap policy as an intra-group IOI.
    """
    if interval is None:
        return None
    pulse = Fraction(interval)
    if pulse <= 0 or pulse.denominator % 3 != 0:
        return None
    return pulse


def _duration(
    raw,
    onset,
    next_onset,
    overlaps,
    family,
    *,
    preserve=False,
    measure_length=Fraction(4),
    beat_length=Fraction(1),
    release_reason=None,
    release_at=None,
    settings=None,
    local_pulse=None,
):
    settings = _settings(settings)
    if settings.preserve_performed_durations():
        preserve = True
    unit = Fraction(1, 48) if family == "triplet" else Fraction(1, 16)
    onset = Fraction(onset) if not isinstance(onset, Fraction) else onset
    measure_length = Fraction(measure_length)
    beat_length = Fraction(beat_length)
    named = {Fraction(n, d) for d in (1, 2, 4, 8, 16)
             for n in (1, 2, 3, 4, 6, 8, 12, 16)}
    if family == "triplet":
        named.update(Fraction(n, d) for d in (6, 12, 24, 48) for n in (1, 2, 4, 8, 16))
    # Long sustains remain possible and will be split into barline ties.
    named.add(max(unit, round(raw / float(unit)) * unit))
    # Metrical releases near integer/half/dotted boundaries and bar ends.
    for boundary in (1, 2, 3, 4, 5, 6, 7, 8, Fraction(3, 2), Fraction(1, 2), Fraction(3, 4)):
        if abs(raw - float(boundary)) <= 0.35:
            named.add(Fraction(boundary))
    bar_pos = onset % measure_length if measure_length > 0 else Fraction(0)
    to_bar = measure_length - bar_pos
    if to_bar > 0 and abs(raw - float(to_bar)) <= 0.35:
        named.add(to_bar)
    # max_dots changes spelling (ties), not the selected musical duration.
    if preserve:
        nearest = min(
            named,
            key=lambda d: (abs(float(d) - raw), d.denominator, d),
        )
        # Literal always keeps the nearest named value. Saved v1 Readable
        # only short-circuits on an exact named duration, matching main.
        if settings.preserve_performed_durations() or abs(float(nearest) - raw) < 1e-7:
            return nearest
    # Reattack / pedal-tail means write to the next accepted attack. Independent
    # overlapping unisons and long holds through a same-pitch interrupter are
    # classified as overlapping_repeat before this point, so they never cap.
    if (
        settings.overlap_handling != OverlapHandling.PRESERVE
        and release_reason in {"pedal_tail", "reattack"}
        and isinstance(release_at, Fraction)
    ):
        cap = release_at - onset
        if cap > 0:
            return cap
    if isinstance(next_onset, Fraction) or next_onset is None:
        effective_next = next_onset
    else:
        effective_next = Fraction(next_onset)
    written_overlap = overlaps if preserve else _written_overlap(
        raw,
        onset,
        effective_next,
        overlaps,
        release_reason=release_reason,
        settings=settings,
    )
    if effective_next is not None and not written_overlap:
        cap = effective_next - onset
        named = {d for d in named if d <= cap + Fraction(1, 10**9)}
        if cap > 0:
            named.add(cap)
            if abs(float(cap) - raw) <= max(0.95, raw * 0.55):
                named.add(cap)
    if not named:
        named = {max(unit, round(raw / float(unit)) * unit)}
    filled = _readable_v2_fill_small_release_gap(
        raw,
        onset,
        effective_next,
        to_bar,
        release_reason=release_reason,
        settings=settings,
        local_pulse=local_pulse if family == "triplet" else None,
        beat_length=beat_length,
        measure_length=measure_length,
    )
    if filled is not None:
        return filled
    return min(
        named,
        key=lambda d: _duration_spelling_cost(
            raw,
            onset,
            d,
            family,
            measure_length=measure_length,
            beat_length=beat_length,
        ),
    )


def _metrical_duration_slots(onset, to_bar, beat_length, next_onset, measure_length):
    """Release targets on actual beats and bars, not onset + N beats.

    An offbeat onset of 0.25 plus one beat lands at 1.25, which is not a
    metrical boundary. Candidates are the next attack, the next beat or bar
    *position*, and the remaining distance to the barline.
    """
    slots = []
    onset = Fraction(onset)
    if next_onset is not None:
        ioi = Fraction(next_onset) - onset
        if ioi > 0:
            slots.append(ioi)
    if beat_length is not None and Fraction(beat_length) > 0 and measure_length is not None:
        measure_length = Fraction(measure_length)
        beat = Fraction(beat_length)
        if measure_length > 0:
            bar_pos = onset % measure_length
            bar_start = onset - bar_pos
            k = 1
            limit = Fraction(to_bar) if to_bar is not None and Fraction(to_bar) > 0 else measure_length
            while k <= 32:
                target = bar_start + beat * k
                if target <= onset + Fraction(1, 10**9):
                    k += 1
                    continue
                dur = target - onset
                if next_onset is not None and onset + dur > Fraction(next_onset) + Fraction(1, 10**9):
                    break
                slots.append(dur)
                if dur >= limit - Fraction(1, 10**9):
                    break
                k += 1
    if to_bar is not None and Fraction(to_bar) > 0:
        slots.append(Fraction(to_bar))
    return slots


def _readable_v2_fill_small_release_gap(
    raw,
    onset,
    next_onset,
    to_bar,
    *,
    release_reason,
    settings,
    local_pulse=None,
    beat_length=None,
    measure_length=None,
):
    """Readable: leftover gaps that are articulation, not rests.

    Detached regular notes fill to the next attack, beat, or bar when the
    leftover is a small fraction of that slot and smaller than the sounding
    note. Intentional short notes plus rests (remaining ≥ sounding duration)
    stay distinct. Independent holds are left alone. Never extend past the
    next attack or the barline.

    ``performance-score-1`` does not run this pass (saved-score compatibility).
    Tuplets use ``local_pulse`` for group endings; locked timing is preserved
    by ``as_score_fraction`` before this function is called.
    """
    if not settings.uses_improved_readable():
        return None
    if release_reason in {
        "independent_hold",
        "multi_attack_hold",
        "overlapping_repeat",
        "pedal_tail",
        "reattack",
    }:
        return None
    sixteenth = 0.25
    slots = []
    pulse = _triplet_local_pulse(local_pulse)
    if pulse is not None:
        remaining = float(pulse) - float(raw)
        if 0 <= remaining < sixteenth:
            written_end = Fraction(onset) + pulse
            if next_onset is None or written_end <= Fraction(next_onset) + Fraction(1, 10**9):
                return pulse
    if settings.uses_phrase_readable():
        slots.extend(
            _metrical_duration_slots(
                onset, to_bar, beat_length, next_onset, measure_length
            )
        )
    else:
        if next_onset is not None:
            ioi = Fraction(next_onset) - Fraction(onset)
            if ioi > 0:
                slots.append(ioi)
        if beat_length is not None and Fraction(beat_length) > 0:
            unit = Fraction(beat_length)
            step = 1
            limit = Fraction(to_bar) if to_bar is not None and Fraction(to_bar) > 0 else unit * 8
            while True:
                slot = unit * step
                if slot > limit + Fraction(1, 10**9):
                    break
                slots.append(slot)
                step += 1
                if step > 16:
                    break
        if to_bar is not None and Fraction(to_bar) > 0:
            slots.append(Fraction(to_bar))
    best = None
    for slot in slots:
        if slot <= 0:
            continue
        if next_onset is not None and Fraction(onset) + slot > Fraction(next_onset) + Fraction(1, 10**9):
            continue
        remaining = float(slot) - float(raw)
        if _readable_v2_gap_is_articulation(raw, remaining, float(slot), sixteenth):
            if best is None or slot < best:
                best = slot
    return best


def _readable_v2_gap_is_articulation(raw, remaining, slot, sixteenth):
    """Leftover is performance release, not a written rest.

    Detached quarters (small leftover on a beat) fill. A note that is as
    short as the leftover (sixteenth plus rest) stays a rest. Relative leftover
    must stay under one-fifth of the written slot so 1.75→2.0 can fill while
    0.75+rest on a quarter does not. Triplet group-ends use ``local_pulse``.
    """
    raw_f = Fraction(raw).limit_denominator(64)
    rem_f = Fraction(remaining).limit_denominator(64)
    slot_f = Fraction(slot).limit_denominator(64)
    if slot_f <= 0 or rem_f < 0:
        return False
    if rem_f >= raw_f:
        return False
    if rem_f / slot_f >= Fraction(1, 5):
        return False
    # An eighth rest (0.5) is already a written rest, not a release. Allow
    # 1.75→2.0 (0.25 leftover) without filling 2.5→3.0.
    if rem_f >= Fraction(7, 16):
        return False
    return True


_SHARED_BEAT_WINDOW = 0.13
_CHORD_COINCIDENCE_WINDOW = 0.08
_CHORD_UNIFY_SPREAD = 0.5
_CHORD_UNIFY_RELATIVE = 0.18
_CHORD_COMPACT_SPAN = 14

_PHRASE_PULSES = (
    Fraction(1),
    Fraction(1, 2),
    Fraction(1, 4),
    Fraction(1, 8),
    Fraction(1, 3),
    Fraction(2, 3),
    Fraction(1, 6),
    Fraction(3, 4),
    Fraction(3, 2),
    Fraction(2),
    Fraction(3),
    Fraction(4),
)


def _snap_phrase_pulse(ioi):
    if ioi is None or ioi <= 0:
        return None
    best = None
    for pulse in _PHRASE_PULSES:
        err = abs(float(ioi) - float(pulse))
        if err <= 0.08 and (best is None or err < best[0]):
            best = (err, pulse)
    return None if best is None else best[1]


def _measure_number(onset, measure_length) -> int:
    if measure_length is None:
        return 1
    length = Fraction(measure_length)
    if length <= 0:
        return 1
    return int(Fraction(onset) / length) + 1


def _settings_at_onset(settings, onset, measure_length) -> NotationSettings:
    return settings.resolved_for_measure(_measure_number(onset, measure_length))


def _has_readable_override(settings) -> bool:
    return any(
        override.interpretation == Interpretation.READABLE
        for override in (settings.measure_overrides or ())
        if override.interpretation is not None
    )


def _attack_groups_in_voice(ordered, exact):
    """Same-onset different-pitch members in one musical voice are one attack.

    Overlapping unisons (same pitch) stay separate. A long inner hold that
    merely shares an onset with shorter chord mates is not one attack: duration
    spread is the evidence that the lines are independent.
    """
    groups = []
    for ev in ordered:
        onset = exact[ev.note_id][0]
        duration = exact[ev.note_id][1]
        if groups:
            prev = groups[-1]
            prev_onset = exact[prev[0].note_id][0]
            if abs(float(onset) - float(prev_onset)) <= 1e-9 and all(
                ev.pitch != other.pitch for other in prev
            ):
                durs = [exact[other.note_id][1] for other in prev] + [duration]
                spread = float(max(durs) - min(durs))
                if spread < _CHORD_UNIFY_SPREAD:
                    prev.append(ev)
                    continue
        groups.append([ev])
    return groups


def _phrase_readable_at(attack, exact, settings, measure_length) -> bool:
    onset = exact[attack[0].note_id][0]
    return _settings_at_onset(settings, onset, measure_length).uses_phrase_readable()


def _is_phrase_protected(ev, exact, settings, measure_length) -> bool:
    if getattr(ev, "score_timing_locked", False):
        return True
    return not _settings_at_onset(
        settings, exact[ev.note_id][0], measure_length
    ).uses_phrase_readable()


def _next_later_attack(phrase, index, exact):
    onset = exact[phrase[index][0].note_id][0]
    for later in phrase[index + 1 :]:
        later_onset = exact[later[0].note_id][0]
        if later_onset > onset:
            return later[0]
    return None


def _split_voice_phrases(attacks, exact, settings=None, measure_length=None):
    """Split a voice on irregular onset gaps and interpretation boundaries."""
    if not attacks:
        return []
    if len(attacks) == 1:
        return [list(attacks)]
    phrases = []
    current = [attacks[0]]
    seen = []
    prev_flag = (
        _phrase_readable_at(attacks[0], exact, settings, measure_length)
        if settings is not None
        else True
    )
    for attack in attacks[1:]:
        onset = float(exact[attack[0].note_id][0])
        prev_onset = float(exact[current[-1][0].note_id][0])
        ioi = onset - prev_onset
        flag = (
            _phrase_readable_at(attack, exact, settings, measure_length)
            if settings is not None
            else prev_flag
        )
        recent = seen[-3:] or ([ioi] if ioi > 0 else [0.0])
        typical = sorted(recent)[len(recent) // 2]
        gap = (
            ioi > 0
            and typical > 0
            and ioi >= max(2.0, typical * 1.85)
            and ioi - typical >= 0.75
        )
        if flag != prev_flag or gap:
            phrases.append(current)
            current = [attack]
            seen = []
        else:
            current.append(attack)
            if ioi > 0:
                seen.append(ioi)
        prev_flag = flag
    phrases.append(current)
    return phrases


def _phrase_ioi(ev, nxt, exact, pulse, to_bar):
    onset = exact[ev.note_id][0]
    if nxt is not None:
        ioi = exact[nxt.note_id][0] - onset
        if ioi > 0:
            return Fraction(ioi)
    if pulse is not None and pulse > 0:
        if to_bar is None or pulse <= Fraction(to_bar) + Fraction(1, 10**9):
            return pulse
    return None


def _is_phrase_detached(raw, ioi):
    """True when a leftover looks like articulation of a repeated written value.

    Mixed-release quarters (0.74–0.83 of the pulse) fill. Short notes with a
    real rest (~0.64 of an irregular IOI, or remaining ≥ sounding duration)
    stay short. This is stricter than the local leftover threshold so a
    phrase of similar releases can still unify 0.77/0.83 without absorbing
    genuine short-note/rest patterns.
    """
    if ioi is None or ioi <= 0:
        return False
    rem = float(ioi) - float(raw)
    if rem < -1e-9:
        return False
    if rem >= float(raw) - 1e-9:
        return False
    if float(raw) / float(ioi) < 0.74:
        return False
    return True


def _readable_phrase_unify_durations(
    events,
    exact,
    settings,
    raw_by_id,
    *,
    measure_length=Fraction(4),
    beat_length=Fraction(1),
):
    """Rewrite a voice's written durations jointly over a measure or short phrase.

    Local leftover thresholds can alternate 0.75 and 1.0 on a detached quarter
    line. When neighboring attacks share pulse and similar release ratios,
    prefer one conventional value. A chord is one attack. Isolated shorts,
    independent holds, locked timing, Literal override measures, and
    substantial pauses stay put and cap neighbors.
    """
    settings = _settings(settings)
    adjustments = {}
    if not settings.uses_phrase_readable() and not _has_readable_override(settings):
        return events, exact, adjustments
    measure_length = Fraction(measure_length)
    groups = defaultdict(list)
    for ev in events:
        line = ev.musical_voice if ev.musical_voice is not None else ev.voice
        groups[(ev.hand, line, ev.source_track_id)].append(ev)
    new_exact = dict(exact)
    for group in groups.values():
        ordered = sorted(group, key=lambda e: (exact[e.note_id][0], e.pitch, e.note_id))
        attacks = _attack_groups_in_voice(ordered, exact)
        for phrase in _split_voice_phrases(
            attacks, exact, settings=settings, measure_length=measure_length
        ):
            if len(phrase) < 2:
                continue
            snapped_iois = []
            for attack, nxt in zip(phrase, phrase[1:]):
                delta = exact[nxt[0].note_id][0] - exact[attack[0].note_id][0]
                if delta <= 0:
                    continue
                snapped = _snap_phrase_pulse(delta)
                if snapped is not None:
                    snapped_iois.append(snapped)
            if not snapped_iois:
                continue
            pulse = max(set(snapped_iois), key=snapped_iois.count)
            needed = max(2, (len(phrase) * 3 + 4) // 5)
            if snapped_iois.count(pulse) < needed:
                continue
            eligible = []
            for index, attack in enumerate(phrase):
                nxt = _next_later_attack(phrase, index, new_exact)
                onset = new_exact[attack[0].note_id][0]
                bar_pos = onset % measure_length if measure_length > 0 else Fraction(0)
                to_bar = measure_length - bar_pos if measure_length > 0 else None
                ioi = _phrase_ioi(attack[0], nxt, new_exact, pulse, to_bar)
                members = []
                for ev in attack:
                    if _is_phrase_protected(ev, new_exact, settings, measure_length):
                        continue
                    source = raw_by_id.get(ev.note_id)
                    raw = source.duration_beats if source is not None else float(ev.duration_beats)
                    if ioi is None or not _is_phrase_detached(raw, ioi):
                        continue
                    if nxt is None and float(ioi) - float(raw) >= 0.5:
                        continue
                    members.append((ev, ioi, raw))
                if members:
                    eligible.append(members)
            if len(eligible) < needed:
                continue
            candidates = [item for members in eligible for item in members]
            ratios = [c[2] / float(c[1]) for c in candidates]
            if max(ratios) - min(ratios) > 0.22:
                continue
            for ev, ioi, raw in candidates:
                onset, duration, family, group_id = new_exact[ev.note_id]
                chosen = Fraction(ioi).limit_denominator(48)
                if chosen <= 0 or abs(float(chosen) - float(duration)) <= 1e-9:
                    continue
                new_exact[ev.note_id] = (onset, chosen, family, group_id)
                adjustments[ev.note_id] = {
                    "from": float(duration),
                    "to": float(chosen),
                    "reason": "readable_phrase_duration",
                    "pulse": float(pulse),
                    "performed": float(raw),
                }
    if not adjustments:
        return events, exact, adjustments
    updated = []
    for ev in events:
        if ev.note_id not in adjustments:
            updated.append(ev)
            continue
        duration = new_exact[ev.note_id][1]
        updated.append(copy_event(ev, duration_beats=float(duration)))
    return updated, new_exact, adjustments


_DETACHED_PULSE_MIN_ATTACKS = 2
_DETACHED_PULSE_MIN_ELIGIBLE_ONSETS = 2
_DETACHED_PULSE_ELIGIBLE_SHARE = 0.5
_DETACHED_RATIO_LO = 0.12
_DETACHED_RATIO_HI = 0.45
_DETACHED_RATIO_SPREAD = 0.30
_DETACHED_PITCH_GAP = 8


def _cluster_unique_onsets(exact, events):
    clustered = []
    for onset in sorted(Fraction(exact[ev.note_id][0]) for ev in events):
        if clustered and abs(float(onset) - float(clustered[-1])) <= _CHORD_COINCIDENCE_WINDOW:
            continue
        clustered.append(onset)
    return clustered


def _next_clustered_onset(onsets, current):
    for onset in onsets:
        if float(onset) > float(current) + 1e-9:
            return onset
    return None


def _detached_line_key(ev) -> tuple:
    line = ev.musical_voice if ev.musical_voice is not None else ev.voice
    return (ev.hand, line, ev.source_track_id)


def _on_pulse_grid(onset, pulse, phase=0):
    if pulse is None or pulse <= 0:
        return False
    width = float(pulse)
    rel = (float(onset) - float(phase)) % width
    return min(rel, width - rel) <= _CHORD_COINCIDENCE_WINDOW


def _onset_phase(onsets, pulse):
    if not onsets or pulse is None or pulse <= 0:
        return 0
    return float(onsets[0]) % float(pulse)


def _detached_pulse_of(onsets):
    iois = [later - earlier for earlier, later in zip(onsets, onsets[1:]) if later > earlier]
    snapped = []
    for ioi in iois:
        value = _snap_phrase_pulse(ioi)
        if value is not None:
            snapped.append(value)
    if not snapped:
        return None
    pulse = max(set(snapped), key=snapped.count)
    needed = max(1, (len(snapped) * 3 + 4) // 5)
    if snapped.count(pulse) < needed:
        return None
    return pulse


def _written_detached_pulse(stream_pulse, onsets, beat_length):
    """Prefer the metrical beat when a sparse on-beat stream's IOI is longer.

    Bass every three beats still writes quarters plus rests. A regular
    subdivision faster than the beat keeps that subdivision.
    """
    beat = Fraction(beat_length) if beat_length and beat_length > 0 else None
    if stream_pulse is None:
        if beat is not None and onsets and all(_on_pulse_grid(onset, beat) for onset in onsets):
            return beat
        return None
    if (
        beat is not None
        and stream_pulse > beat + Fraction(1, 10**9)
        and all(_on_pulse_grid(onset, beat) for onset in onsets)
    ):
        return beat
    return stream_pulse


def _is_detached_hold(ev, raw, pulse, onset, next_onset, exact):
    if float(raw) >= 2.0 * float(pulse) - 1e-9:
        return True
    written = exact[ev.note_id][1]
    if float(written) >= 2.0 * float(pulse) - 1e-9:
        return True
    if next_onset is not None and float(onset) + float(raw) > float(next_onset) + 0.04:
        return True
    return False


def _pitch_bands(events, *, gap=_DETACHED_PITCH_GAP):
    pitches = sorted({ev.pitch for ev in events})
    if not pitches:
        return []
    cuts = [0]
    for index, (prev, cur) in enumerate(zip(pitches, pitches[1:]), start=1):
        if cur - prev >= gap:
            cuts.append(index)
    cuts.append(len(pitches))
    bands = []
    for start, end in zip(cuts, cuts[1:]):
        band_pitches = set(pitches[start:end])
        bands.append([ev for ev in events if ev.pitch in band_pitches])
    return [band for band in bands if band]


def _band_onset_keys(band, exact):
    return {round(float(onset), 4) for onset in _cluster_unique_onsets(exact, band)}


def _median_onset_leap(events):
    by_onset = defaultdict(list)
    for ev in events:
        by_onset[round(ev.start_beat, 4)].append(ev.pitch)
    contour = [mean(pitches) for _, pitches in sorted(by_onset.items())]
    leaps = [abs(later - earlier) for earlier, later in zip(contour, contour[1:])]
    if not leaps:
        return 0.0
    leaps.sort()
    return leaps[len(leaps) // 2]


def _split_interlocking_layers(events, exact):
    """Split complementary registers that do not share attacks.

    Coordinated chords and octaves share onsets and stay one stream. A
    connected arpeggio (small time-ordered leaps) also stays one stream.
    Offbeat accompaniment in another register is a separate rhythmic stream
    even on the same staff or musical_voice.
    """
    bands = _pitch_bands(events)
    if len(bands) <= 1:
        return [events]
    parent = list(range(len(bands)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    keys = [_band_onset_keys(band, exact) for band in bands]
    for i in range(len(bands)):
        for j in range(i + 1, len(bands)):
            if keys[i] & keys[j]:
                union(i, j)
    merged = defaultdict(list)
    for index, band in enumerate(bands):
        merged[find(index)].extend(band)
    layers = list(merged.values())
    if len(layers) <= 1:
        return [events]
    if _median_onset_leap(events) <= _DETACHED_PITCH_GAP:
        return [events]
    return layers


def _detached_stream_groups(events, exact):
    groups = defaultdict(list)
    for ev in events:
        groups[_detached_line_key(ev)].append(ev)
    streams = []
    for group in groups.values():
        streams.extend(_split_interlocking_layers(group, exact))
    return streams


def _detached_mark(ev):
    if (ev.articulation_source or "") == "user_edit":
        return ev.articulation or None, "user_edit"
    if ev.articulation:
        source = ev.articulation_source or "supplied"
        return ev.articulation, source
    return "staccato", "inferred"


def _readable_unify_detached_pulse(
    events,
    exact,
    settings,
    raw_by_id,
    *,
    measure_length=Fraction(4),
    beat_length=Fraction(1),
):
    """Rewrite strongly detached pulse playing as conventional written values.

    Pulse and duration are inferred inside coherent streams: a chord is one
    attack, and a foreign voice must not truncate the written value. Short
    phrases fill when metrical position, a repeated pulse, and release
    consistency agree. Skipped beats, mixed-release interiors, locked timing,
    and Literal measures stay put. Readable convention, not recovered intent.
    """
    settings = _settings(settings)
    adjustments = {}
    if not settings.uses_phrase_readable() and not _has_readable_override(settings):
        return events, exact, adjustments
    measure_length = Fraction(measure_length)
    beat_length = Fraction(beat_length) if beat_length else Fraction(1)
    new_exact = dict(exact)
    updated_by_id = {}
    for stream in _detached_stream_groups(events, exact):
        ordered = sorted(stream, key=lambda e: (exact[e.note_id][0], e.pitch, e.note_id))
        attacks = _attack_groups_in_voice(ordered, exact)
        pulse_hint = None
        hint_phase = 0.0
        for phrase in _split_voice_phrases(
            attacks, exact, settings=settings, measure_length=measure_length
        ):
            members = [ev for attack in phrase for ev in attack]
            onsets = _cluster_unique_onsets(new_exact, members)
            neighbor = pulse_hint is not None
            if len(onsets) < (_DETACHED_PULSE_MIN_ATTACKS if not neighbor else 1):
                pulse_hint = None
                continue
            stream_pulse = _detached_pulse_of(onsets)
            pulse = _written_detached_pulse(stream_pulse, onsets, beat_length)
            if pulse is None and neighbor:
                pulse = pulse_hint
            if pulse is None or pulse <= 0:
                pulse_hint = None
                continue
            phase = _onset_phase(onsets, pulse) if not neighbor else hint_phase
            eligible = []
            eligible_onsets = set()
            for ev in members:
                if _is_phrase_protected(ev, new_exact, settings, measure_length):
                    continue
                onset = new_exact[ev.note_id][0]
                if not _on_pulse_grid(onset, pulse, phase):
                    continue
                nxt = _next_clustered_onset(onsets, onset)
                source = raw_by_id.get(ev.note_id)
                raw = source.duration_beats if source is not None else float(ev.duration_beats)
                if _is_detached_hold(ev, raw, pulse, onset, nxt, new_exact):
                    continue
                ratio = float(raw) / float(pulse)
                if ratio < _DETACHED_RATIO_LO or ratio > _DETACHED_RATIO_HI:
                    continue
                eligible.append((ev, onset, nxt, raw, ratio))
                eligible_onsets.add(round(float(onset), 6))
            min_eligible = 1 if neighbor else _DETACHED_PULSE_MIN_ELIGIBLE_ONSETS
            if len(eligible_onsets) < min_eligible:
                pulse_hint = None
                continue
            if not neighbor and len(eligible_onsets) / len(onsets) < _DETACHED_PULSE_ELIGIBLE_SHARE - 1e-9:
                pulse_hint = None
                continue
            ratios = [item[4] for item in eligible]
            if max(ratios) - min(ratios) > _DETACHED_RATIO_SPREAD:
                pulse_hint = None
                continue
            filled = False
            for ev, onset, nxt, raw, _ratio in eligible:
                bar_pos = onset % measure_length if measure_length > 0 else Fraction(0)
                to_bar = measure_length - bar_pos if measure_length > 0 else None
                chosen = Fraction(pulse).limit_denominator(48)
                truncated_by_stream = False
                if nxt is not None:
                    until_next = Fraction(nxt) - Fraction(onset)
                    if until_next < chosen:
                        chosen = until_next
                        truncated_by_stream = True
                # A barline is an engraving boundary. Duration inference stays
                # on the logical note; canonical spelling splits it into ties.
                # The last attack of a phrase does not invent a continuation
                # into empty following space.
                if nxt is None and to_bar is not None and to_bar > 0:
                    chosen = min(chosen, Fraction(to_bar))
                if chosen <= 0:
                    continue
                if truncated_by_stream and float(chosen) < float(pulse) * 0.75 - 1e-9:
                    continue
                current_onset, duration, family, group_id = new_exact[ev.note_id]
                mark, source = _detached_mark(ev)
                filled = True
                if abs(float(chosen) - float(duration)) <= 1e-9:
                    if source != "user_edit" and not ev.articulation:
                        updated_by_id[ev.note_id] = copy_event(
                            ev, articulation=mark, articulation_source=source
                        )
                    continue
                new_exact[ev.note_id] = (current_onset, chosen, family, group_id)
                if source == "user_edit":
                    updated = copy_event(ev, duration_beats=float(chosen))
                else:
                    updated = copy_event(
                        ev,
                        duration_beats=float(chosen),
                        articulation=mark,
                        articulation_source=source,
                    )
                updated_by_id[ev.note_id] = updated
                adjustments[ev.note_id] = {
                    "from": float(duration),
                    "to": float(chosen),
                    "reason": "readable_detached_pulse",
                    "pulse": float(pulse),
                    "performed": float(raw),
                    "articulation": updated.articulation,
                    "articulation_source": updated.articulation_source,
                }
            if filled:
                pulse_hint = pulse
                hint_phase = phase
            else:
                pulse_hint = None
    if not adjustments and not updated_by_id:
        return events, exact, adjustments
    updated = []
    for ev in events:
        replacement = updated_by_id.get(ev.note_id)
        updated.append(replacement if replacement is not None else ev)
    return updated, new_exact, adjustments


def _voice_is_fast_near(ev, ordered_same_voice, *, window=0.35) -> bool:
    """True when the local same-voice stream is a rapid figure, not a held tone.

    Simultaneous chord mates do not count; only sequential attacks in the
    local window are a fast figure.
    """
    neighbors = sum(
        1
        for other in ordered_same_voice
        if other.note_id != ev.note_id
        and _CHORD_COINCIDENCE_WINDOW < abs(other.start_beat - ev.start_beat) < window
    )
    return neighbors >= 2


def _readable_align_shared_onsets(
    onset_by_id,
    events,
    roles,
    *,
    max_move,
    settings,
    measure_length=None,
):
    """Align near-simultaneous cross-line attacks onto one simpler Readable beat.

    Covers delayed melody entries against bass/accompaniment when the performed
    gap is within a 32nd-ish window. Literal mode, locked timing, tuplets, and
    fast local streams are left alone. Saved v1 Readable still runs this
    cross-line path; chord coincidence stays on v2 and current.
    """
    settings = _settings(settings)
    adjustments = {}

    def _event_local(ev):
        onset = onset_by_id.get(ev.note_id, ev.start_beat)
        return _settings_at_onset(settings, onset, measure_length)

    def _onset_readable(ev) -> bool:
        if getattr(ev, "score_timing_locked", False):
            return False
        return _event_local(ev).interpretation == Interpretation.READABLE

    by_voice = defaultdict(list)
    for ev in events:
        by_voice[(ev.hand, ev.voice, ev.source_track_id)].append(ev)
    for group in by_voice.values():
        group.sort(key=lambda e: (e.start_beat, e.pitch, e.note_id))

    ordered = sorted(events, key=lambda e: (e.start_beat, e.pitch, e.note_id))
    clusters = []
    for ev in ordered:
        if not _onset_readable(ev):
            continue
        if clusters and ev.start_beat - clusters[-1][0].start_beat <= _SHARED_BEAT_WINDOW:
            clusters[-1].append(ev)
        else:
            clusters.append([ev])

    for cluster in clusters:
        if len(cluster) < 2:
            continue
        if any(getattr(ev, "score_timing_locked", False) for ev in cluster):
            continue
        hands = {ev.hand for ev in cluster}
        role_names = {roles.get(ev.note_id, ("accompaniment",))[0] for ev in cluster}
        cross_line = len(hands) >= 2 or (
            {"melody"} & role_names
            and role_names & {"bass", "accompaniment"}
        )
        members = cluster
        reason = "readable_shared_beat"
        if not cross_line:
            if not all(_event_local(ev).uses_improved_readable() for ev in cluster):
                continue
            members = _compact_chord_coincidence(cluster)
            if len(members) < 2:
                continue
            reason = "readable_chord_coincidence"
        if any(
            _voice_is_fast_near(ev, by_voice[(ev.hand, ev.voice, ev.source_track_id)])
            for ev in members
        ):
            continue
        current = [onset_by_id[ev.note_id] for ev in members]
        if len(set(current)) == 1:
            continue
        # Do not flatten an already-exact tuplet spelling. Humanized chord
        # members can land on a 1/24 grid without being a tuplet figure.
        if cross_line and any(onset.denominator % 3 == 0 for onset in current):
            continue

        raw_min = min(ev.start_beat for ev in members)
        raw_mean = mean(ev.start_beat for ev in members)
        anchors = set(current)
        for center in (raw_min, raw_mean):
            for denominator in (1, 2, 4):
                anchors.add(Fraction(round(center * denominator), denominator))

        best = None
        best_cost = None
        for cand in anchors:
            if cand < 0 or cand.denominator % 3 == 0:
                continue
            if any(abs(float(cand) - ev.start_beat) > max_move for ev in members):
                continue
            cost = sum(abs(float(cand) - ev.start_beat) for ev in members)
            cost += 0.012 * max(0, cand.denominator - 1)
            if any(
                onset_by_id[ev.note_id] == cand and cand.denominator <= 2
                for ev in members
            ):
                cost -= 0.05
            role_boost = any(
                roles.get(ev.note_id, ("",))[0] in {"bass", "accompaniment"}
                and abs(float(cand) - ev.start_beat)
                <= abs(float(onset_by_id[ev.note_id]) - ev.start_beat) + 1e-9
                for ev in members
            )
            if role_boost and cand.denominator <= 2:
                cost -= 0.03
            if best is None or cost < best_cost:
                best, best_cost = cand, cost
        if best is None:
            continue
        for ev in members:
            prev = onset_by_id[ev.note_id]
            if prev == best:
                continue
            onset_by_id[ev.note_id] = best
            adjustments[ev.note_id] = {
                "from": float(prev),
                "to": float(best),
                "reason": reason,
            }
    return onset_by_id, adjustments


def _compact_chord_coincidence(cluster):
    """Humanized same-hand chord members, not a 32nd displacement or mixed-release.

    Window is tighter than cross-line shared-beat alignment so deliberate
    syncopation and fast figures stay put.
    """
    if len({ev.hand for ev in cluster}) != 1:
        return []
    ordered = sorted(cluster, key=lambda e: (e.start_beat, e.pitch, e.note_id))
    first = ordered[0].start_beat
    members = [ev for ev in ordered if ev.start_beat - first <= _CHORD_COINCIDENCE_WINDOW]
    if len(members) < 2:
        return []
    pitches = [ev.pitch for ev in members]
    if max(pitches) - min(pitches) > _CHORD_COMPACT_SPAN:
        return []
    durs = [float(ev.duration_beats) for ev in members]
    if max(durs) - min(durs) >= 0.85:
        return []
    if len({ev.pitch for ev in members}) != len(members):
        return []
    if not _members_overlap_as_chord(members):
        return []
    return members


def _members_overlap_as_chord(members) -> bool:
    """True when staggered attacks share a release, not a consecutive run.

    Pitches 60/64/67 at 0, 1/16, 1/8 each lasting 1/16 are a run: duration
    does not outlast the onset spread and overlap is empty. A humanized
    C–E–G with ~2-beat members and 30–50ms stagger overlaps substantially.
    """
    if len(members) < 2:
        return False
    ordered = sorted(members, key=lambda e: (e.start_beat, e.pitch, e.note_id))
    spread = ordered[-1].start_beat - ordered[0].start_beat
    min_dur = min(float(e.duration_beats) for e in ordered)
    if min_dur <= spread + 1e-9:
        return False
    first = ordered[0]
    first_end = first.start_beat + first.duration_beats
    for other in ordered[1:]:
        other_end = other.start_beat + other.duration_beats
        overlap = min(first_end, other_end) - max(first.start_beat, other.start_beat)
        if overlap <= 0:
            return False
        if overlap < 0.5 * min(first.duration_beats, other.duration_beats):
            return False
    return True


def _readable_unify_chord_durations(events, exact, settings, measure_length=None):
    """Give humanized chord mates one written duration when evidence agrees.

    Independent mixed-release holds, overlapping unisons, and tuplets of
    different families stay distinct. Literal mode does not rewrite durations.
    """
    settings = _settings(settings)
    adjustments = {}
    if not settings.uses_improved_readable() and not _has_readable_override(settings):
        return events, exact, adjustments
    groups = defaultdict(list)
    for ev in events:
        onset = exact[ev.note_id][0]
        line = ev.musical_voice if ev.musical_voice is not None else ev.voice
        groups[(ev.hand, line, onset)].append(ev)
    new_exact = dict(exact)
    for members in groups.values():
        members = [
            ev
            for ev in members
            if not getattr(ev, "score_timing_locked", False)
            and _settings_at_onset(
                settings, exact[ev.note_id][0], measure_length
            ).uses_improved_readable()
        ]
        if len(members) < 2:
            continue
        pitches = [m.pitch for m in members]
        if max(pitches) - min(pitches) > _CHORD_COMPACT_SPAN:
            continue
        if len(set(pitches)) != len(members):
            continue
        families = {new_exact[m.note_id][2] for m in members}
        if len(families) > 1:
            continue
        durs = [new_exact[m.note_id][1] for m in members]
        mind, maxd = min(durs), max(durs)
        if maxd - mind <= Fraction(1, 10**9):
            continue
        spread = float(maxd - mind)
        if spread >= _CHORD_UNIFY_SPREAD:
            continue
        if spread / max(float(maxd), 0.25) > _CHORD_UNIFY_RELATIVE:
            continue
        chosen = maxd
        for ev in members:
            onset, duration, family, group_id = new_exact[ev.note_id]
            if duration == chosen:
                continue
            new_exact[ev.note_id] = (onset, chosen, family, group_id)
            adjustments[ev.note_id] = {
                "from": float(duration),
                "to": float(chosen),
                "reason": "readable_chord_duration",
            }
    if not adjustments:
        return events, exact, adjustments
    updated = []
    for ev in events:
        if ev.note_id not in adjustments:
            updated.append(ev)
            continue
        duration = new_exact[ev.note_id][1]
        updated.append(copy_event(ev, duration_beats=float(duration)))
    return updated, new_exact, adjustments


_ORNAMENT_MAX_RAW_DURATION = 0.35
_ORNAMENT_LEAD_WINDOW = 0.30


def _readable_mark_ornaments(
    events, onset_by_id, exact, roles, settings, raw_by_id, measure_length=None
):
    """Label short anticipatory notes as editable ornaments (Readable only).

    Does not delete source attacks. Written duration stays positive so playback
    and export integrity keep the performed attack; decisions expose an
    editable ornament interpretation for the editor.
    """
    settings = _settings(settings)
    marks = {}
    if (
        settings.interpretation != Interpretation.READABLE
        and not _has_readable_override(settings)
    ):
        return marks

    by_hand = defaultdict(list)
    for ev in events:
        by_hand[ev.hand].append(ev)
    for group in by_hand.values():
        group.sort(key=lambda e: (
            raw_by_id.get(e.note_id, e).start_beat,
            e.pitch,
            e.note_id,
        ))

    for _hand, ordered in by_hand.items():
        for index, ev in enumerate(ordered):
            raw = raw_by_id.get(ev.note_id, ev)
            if getattr(raw, "score_timing_locked", False):
                continue
            local = _settings_at_onset(
                settings, onset_by_id.get(ev.note_id, raw.start_beat), measure_length
            )
            if local.interpretation != Interpretation.READABLE:
                continue
            if float(raw.duration_beats) > _ORNAMENT_MAX_RAW_DURATION:
                continue
            # Long written holds (e.g. re-ingested score MIDI) are not ornaments
            # merely because a reviewer described them as short.
            written = exact.get(ev.note_id)
            if written is not None and float(written[1]) > 1.0:
                continue
            primary = None
            for later in ordered[index + 1 :]:
                raw_later = raw_by_id.get(later.note_id, later)
                gap = raw_later.start_beat - raw.start_beat
                if gap < -1e-9:
                    continue
                if gap > _ORNAMENT_LEAD_WINDOW:
                    break
                if float(raw_later.duration_beats) < float(raw.duration_beats) * 1.5:
                    continue
                if later.pitch == ev.pitch:
                    continue
                primary = later
                break
            if primary is None:
                continue
            primary_onset = onset_by_id.get(primary.note_id)
            if primary_onset is None or primary_onset.denominator > 4:
                continue
            role = roles.get(ev.note_id, ("accompaniment",))[0]
            if role == "bass":
                continue
            marks[ev.note_id] = {
                "ornament_style": "acciaccatura",
                "primary_note_id": primary.note_id,
                "editable": True,
                "reason": "short_anticipation_before_pulse",
            }
    return marks


def _score_voices(events, separator):
    worker = separator
    if type(separator) is VoiceSeparator:
        # Keep the configured complexity policy (default 4). Never drop notes
        # to meet it; extra printed lanes are diagnosed on the separator.
        worker = VoiceSeparator(replace(
            separator.config,
            prefer_simple_chords=True,
            overlap_grace_beats=0.10,
        ))
    search = _voice_search_events(events)
    voiced = worker.separate(search)
    if worker is not separator:
        separator.last_diagnostics = list(worker.last_diagnostics)
    by_id = {ev.note_id: ev for ev in voiced}
    restored = []
    for ev in events:
        chosen = by_id.get(ev.note_id)
        if chosen is None:
            restored.append(ev)
            continue
        musical = chosen.musical_voice if chosen.musical_voice is not None else chosen.voice
        restored.append(
            copy_event(
                ev,
                voice=chosen.voice,
                musical_voice=musical,
                voice_confidence=chosen.voice_confidence,
                voice_assigned=True,
                voice_provenance=chosen.voice_provenance or "inferred",
            )
        )
    return restored


def _pulsed_line_evidence(ev, nxt, ordered_same_hand) -> bool:
    """True when shortening is supported by line context, not proximity alone.

    Same-pitch pulse re-attacks count. Different pitches need a prior attack at
    roughly the same spacing and pitch as ``ev`` (an established pulsed line).
    """
    gap = float(nxt.start_beat - ev.start_beat)
    if nxt.pitch == ev.pitch:
        return True
    for prev in ordered_same_hand:
        if prev.start_beat >= ev.start_beat - 1e-9:
            break
        prev_gap = float(ev.start_beat - prev.start_beat)
        if abs(prev_gap - gap) <= 0.12 and abs(prev.pitch - ev.pitch) <= 2:
            return True
    return False


def _release_hypothesis(ev, ordered_same_hand, *, settings=None, pedal=None):
    """Bounded same-hand line/release decision for voice search only.

    Returns (release_target_note_id_or_None, reason, pedal_source).
    Target IDs are resolved to quantized onsets later; performed start/duration
    times are never mutated here.

    Preserves independent holds, near-simultaneous / overlapping unisons, and
    multi-attack sustains. Caps only when line/context evidence supports a
    pedal-like continuation — proximity and duration ratio alone are not enough.
    Inferred pedal tails are labelled ``hypothesis``. Actual CC64 is ``cc64``.
    """
    settings = _settings(settings)
    raw = float(ev.duration_beats)
    end = ev.start_beat + raw
    later = [x for x in ordered_same_hand if x.start_beat > ev.start_beat + 1e-9]
    if not later:
        return None, "phrase_end", None

    first_gap = float(later[0].start_beat - ev.start_beat)
    covered = sum(1 for x in later if x.start_beat < end - 0.04)
    # Held note spanning several later attacks (not a one-pulse pedal tail).
    if covered >= 2 and first_gap > 0 and raw >= first_gap * 4.0:
        return None, "multi_attack_hold", None

    best = None
    for nxt in later:
        gap = float(nxt.start_beat - ev.start_beat)
        if gap > 2.05:
            break
        leap = abs(nxt.pitch - ev.pitch)
        under_sustain = nxt.start_beat < end - 0.04
        nxt_pedal = pedal_down_at(pedal, getattr(nxt, "start_time_sec", None))
        if nxt.pitch == ev.pitch and under_sustain:
            # Near-simultaneous or independently sustained repeated pitch.
            # A hold that continues through a same-pitch interrupter (duration
            # at least twice the gap) is two voices, not a pulsed re-strike.
            if gap <= 0.12 or raw >= gap * 2.0:
                return None, "overlapping_repeat", None
            # Same-pitch re-attack while this key is still down. Write to the
            # next attack; never tie across a genuine re-strike. CC64 is not
            # required — legato MIDI overlaps the same way.
            if 0.20 <= gap <= 2.05 and raw > gap and _pulsed_line_evidence(
                ev, nxt, ordered_same_hand
            ):
                if nxt_pedal:
                    return nxt.note_id, "pedal_tail", "cc64"
                return nxt.note_id, "reattack", None
        if leap > 9:
            continue
        # Different pitch sounding under a sustain is an independent hold
        # unless a pulsed line at this pitch is already established.
        if under_sustain and leap > 0 and not _pulsed_line_evidence(ev, nxt, ordered_same_hand):
            continue
        if not _pulsed_line_evidence(ev, nxt, ordered_same_hand):
            # Opt-in readable: actual pedal may still mark a pulsed continuation.
            if not (
                settings.uses_improved_readable()
                and nxt_pedal
                and 0.20 <= gap <= 2.05
                and gap * 1.25 < raw < gap * 4.0
            ):
                continue
        score = leap + 0.05 * gap
        if best is None or score < best[0]:
            best = (score, nxt, gap, nxt_pedal)
    if best is None:
        return None, "no_line", None
    _score, nxt, gap, nxt_pedal = best
    if 0.20 <= gap <= 2.05 and gap * 1.25 < raw < gap * 4.0:
        source = "cc64" if nxt_pedal else "hypothesis"
        return nxt.note_id, "pedal_tail", source
    return None, "performed_release", None


def _voice_search_events(events):
    """Apply line/release hypotheses for voice search without mutating performed times."""
    by_id = {ev.note_id: ev for ev in events}
    by_stream = defaultdict(list)
    for ev in events:
        by_stream[_stream_key(ev)].append(ev)
    capped = {}
    for group in by_stream.values():
        ordered = sorted(group, key=lambda e: (e.start_beat, e.pitch, e.note_id))
        for ev in ordered:
            target_id, _reason, _source = _release_hypothesis(ev, ordered)
            if target_id is None or target_id not in by_id:
                capped[ev.note_id] = ev
            else:
                gap = float(by_id[target_id].start_beat - ev.start_beat)
                capped[ev.note_id] = copy_event(ev, duration_beats=gap)
    return [capped.get(ev.note_id, ev) for ev in events]


def _conservative_articulations(events, *, settings=None):
    """Keep supplied marks. Do not guess staccato from an isolated rest.

    Phrase-level detached-pulse inference may already have marked staccato
    with ``articulation_source="inferred"``. This pass never invents
    dynamics, slurs, or pedal marks, and it never overwrites a supplied
    or user-edited articulation.
    """
    settings = _settings(settings)
    if settings.interpretation != Interpretation.READABLE:
        return events
    return list(events)


def _stable_lanes(events, exact, grand_staff=True):
    """Allocate printed lanes; musical voice is line identity, not a hard partition.

    Reuses inactive lanes so peak concurrency—not historical voice IDs—drives
    printed voice count. Prefers each musical line's home lane when free, keeps
    chord mates together, and never merges independent unisons.

    Returned events keep ``musical_voice`` / ``voice_provenance`` and set
    ``voice`` to the printed lane ID.
    """
    musical_line = {
        ev.note_id: (
            ev.musical_voice if ev.musical_voice is not None else ev.voice
        )
        for ev in events
    }
    provenance = {
        ev.note_id: (
            ev.voice_provenance
            or ("supplied" if ev.voice_assigned else "inferred")
        )
        for ev in events
    }
    lanes = defaultdict(list)  # staff -> list of event lists (printed lanes)
    home_lane = {}  # (staff, musical_line) -> preferred printed lane
    result = []

    def _lane_free(staff, lane_idx, onset):
        if not lanes[staff][lane_idx]:
            return True
        last = lanes[staff][lane_idx][-1]
        last_onset, last_duration = exact[last.note_id][:2]
        return last_onset + last_duration <= onset

    for ev in sorted(events, key=lambda e: (e.start_beat, e.pitch, e.note_id)):
        staff = staff_for_hand(ev.hand, ev.pitch) if grand_staff else 0
        onset, duration = exact[ev.note_id][:2]
        line = musical_line[ev.note_id]
        selected = None

        # Chord grouping: share the lane of a same-line mate already opened
        # at this onset/duration (different pitch).
        for i, lane in enumerate(lanes[staff]):
            last = lane[-1]
            last_onset, last_duration = exact[last.note_id][:2]
            if (
                last_onset == onset
                and last_duration == duration
                and last.pitch != ev.pitch
                and musical_line[last.note_id] == line
            ):
                selected = i
                break

        if selected is None:
            home = home_lane.get((staff, line))
            if home is not None and home < len(lanes[staff]) and _lane_free(staff, home, onset):
                selected = home

        if selected is None:
            # Reuse any inactive printed lane (lowest index for stability).
            for i in range(len(lanes[staff])):
                if _lane_free(staff, i, onset):
                    selected = i
                    break

        if selected is None:
            selected = len(lanes[staff])
            lanes[staff].append([])

        if (staff, line) not in home_lane:
            home_lane[(staff, line)] = selected
        lanes[staff][selected].append(ev)
        result.append(copy_event(
            ev,
            voice=selected,
            musical_voice=line,
            voice_provenance=provenance[ev.note_id],
        ))
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
        authority = stamped_authority(out) or classify_hand_authority(out)
        if authority is LayoutAuthority.NONE:
            authority = LayoutAuthority.PROVIDER
    out = stamp_authority(out, authority)
    diagnostics = tuple(getattr(voice_separator, "last_diagnostics", None) or ())
    return LayoutResult(
        events=out,
        authority=authority,
        voice_complete=True,
        hand_complete=hands_complete(out) if profile.grand_staff else True,
        diagnostics=diagnostics,
    )


def resolve_layout(raw, profile: ScoreProfile) -> LayoutResult:
    """Keep stamped pipeline layout; infer only when authority is incomplete."""
    prior = stamped_authority(raw)
    if (
        prior is not None
        and prior is not LayoutAuthority.NONE
        and (not profile.grand_staff or hands_complete(raw))
        and voices_complete(raw)
    ):
        events = stamp_authority(
            [copy_event(ev, voice_assigned=True) for ev in raw],
            prior,
        )
        return LayoutResult(
            events=events,
            authority=prior,
            voice_complete=True,
            hand_complete=True if not profile.grand_staff else hands_complete(events),
        )

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
            authority = LayoutAuthority.PROVIDER
            events = stamp_authority(events, authority)
            return LayoutResult(events, authority, True, True)
        separator = VoiceSeparator()
        events = stamp_authority(_score_voices(cleared, separator), LayoutAuthority.INFERRED)
        return LayoutResult(
            events, LayoutAuthority.INFERRED, True, True,
            diagnostics=tuple(separator.last_diagnostics),
        )

    if hands_complete(raw):
        authority = prior or classify_hand_authority(raw)
        events = [copy_event(ev) for ev in raw]
        # Hands already supplied by pipeline/MIDI: keep their voice numbers,
        # including an intentional single voice 0. Do not re-separate.
        if not all(getattr(ev, "voice_assigned", False) for ev in events):
            events = _mark_voices_assigned(events)
        if authority is LayoutAuthority.NONE:
            authority = LayoutAuthority.PROVIDER
        events = stamp_authority(events, authority)
        return LayoutResult(events, authority, True, True)

    if voices_complete(raw):
        hands = HandSeparator().separate(raw)
        events = [
            copy_event(out, voice=src.voice, voice_assigned=True)
            for src, out in zip(raw, hands)
        ]
        events = stamp_authority(events, LayoutAuthority.MIXED)
        return LayoutResult(events, LayoutAuthority.MIXED, True, True)

    separator = VoiceSeparator()
    events = stamp_authority(
        _score_voices(HandSeparator().separate(raw), separator),
        LayoutAuthority.INFERRED,
    )
    return LayoutResult(
        events, LayoutAuthority.INFERRED, True, True,
        diagnostics=tuple(separator.last_diagnostics),
    )


def quantize_notation(
    events,
    meter,
    *,
    config,
    mode=None,
    settings=None,
    tempo_map=None,
    pedal_events=None,
):
    from mir.quantizer import summarize_quantization

    if mode is not None:
        require_production_quantization_mode(mode)
    settings = _settings(settings)

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
    if settings.first_downbeat_beat is not None:
        downbeats = [float(settings.first_downbeat_beat)]
    elif settings.pickup_beats:
        downbeats = [float(settings.pickup_beats)]
    offset = (-min(downbeats)) % meter.measure_quarter_length if downbeats else 0.0
    if abs(offset - meter.measure_quarter_length) < 1e-7:
        offset = 0.0
    score_input = [copy_event(ev, start_beat=ev.start_beat + offset) for ev in raw]
    score_input, profile, collapse_warning = collapse_for_solo_notation(score_input)
    layout = resolve_layout(score_input, profile)
    interpreted = layout.events
    layout_source = layout.layout_source
    measure_length = Fraction(str(meter.measure_quarter_length)).limit_denominator(48)
    beat_length = _beat_length_for_meter(meter)
    voices = defaultdict(list)
    for ev in interpreted:
        staff = staff_for_hand(ev.hand, ev.pitch) if profile.grand_staff else 0
        voices[(staff, ev.voice)].append(ev)

    roles = _phrase_roles(voices, meter.measure_quarter_length)
    release_by_id = _release_decisions(interpreted, settings=settings, pedal=pedal_events)
    # Phase 1: accept quantized onsets for every attack (all voices), then
    # resolve release targets to those onsets before duration spelling.
    onset_jobs = []
    onset_by_id = {}
    policy_exceptions = []
    for key, voice in voices.items():
        groups = []
        for ev in sorted(voice, key=lambda e: (e.start_beat, e.pitch)):
            chord_tolerance = 1e-7 if ev.source_backend == "midi" else 0.04
            if (groups and abs(ev.start_beat - groups[-1][0].start_beat) <= chord_tolerance
                    and all(ev.pitch != other.pitch for other in groups[-1])):
                groups[-1].append(ev)
            else:
                groups.append([ev])
        path = _search(
            groups,
            config.max_onset_move,
            settings=settings,
            measure_length=measure_length,
            exceptions=policy_exceptions,
        )
        for group in groups:
            group_raw = mean(e.start_beat for e in group)
            for row in policy_exceptions:
                if "note_ids" not in row and abs(float(row.get("onset", 0)) - group_raw) < 1e-6:
                    row["note_ids"] = [e.note_id for e in group]
        for i, (group, (onset, family)) in enumerate(zip(groups, path)):
            nxt = path[i + 1][0] if i + 1 < len(path) else None
            neighbors = []
            if nxt is not None:
                same_bar = (
                    measure_length
                    and int(onset / measure_length) == int(nxt / measure_length)
                ) or measure_length is None
                if same_bar:
                    neighbors.append(nxt - onset)
            if i:
                prev = path[i - 1][0]
                same_bar = (
                    measure_length
                    and int(onset / measure_length) == int(prev / measure_length)
                ) or measure_length is None
                if same_bar:
                    neighbors.append(onset - prev)
            if onset.denominator == 1 and any(d.denominator % 3 == 0 for d in neighbors):
                family = "triplet"
            raw_next = min(e.start_beat for e in groups[i + 1]) if nxt is not None else None
            prev_interval = (onset - path[i - 1][0]) if i else None
            for ev in group:
                if getattr(ev, "score_timing_locked", False):
                    onset_by_id[ev.note_id] = as_score_fraction(ev.start_beat, locked=True)
                else:
                    onset_by_id[ev.note_id] = onset
            onset_jobs.append((key, group, onset, family, nxt, raw_next, i, prev_interval))

    onset_by_id, shared_beat_adjustments = _readable_align_shared_onsets(
        onset_by_id,
        interpreted,
        roles,
        max_move=config.max_onset_move,
        settings=settings,
        measure_length=measure_length,
    )

    out, exact = [], {}
    for key, group, onset, family, nxt, raw_next, group_index, prev_interval in onset_jobs:
        # Prefer post-alignment onsets; chord mates still share after search,
        # and shared-beat alignment may unify cross-line attacks.
        aligned = [onset_by_id[ev.note_id] for ev in group]
        onset = aligned[0]
        if nxt is not None:
            # Recompute the next written attack from aligned onsets in this voice.
            voice_events = voices[key]
            later = [
                onset_by_id[ev.note_id]
                for ev in voice_events
                if onset_by_id[ev.note_id] > onset
            ]
            nxt = min(later) if later else None
        bar_number = int(onset / measure_length) + 1 if measure_length > 0 else 1
        local_settings = settings.resolved_for_measure(bar_number)
        for ev in group:
            role, phrase = roles[ev.note_id]
            onset = onset_by_id[ev.note_id]
            if getattr(ev, "score_timing_locked", False):
                locked_onset = onset_by_id[ev.note_id]
                locked_duration = as_score_fraction(ev.duration_beats, positive=True, locked=True)
                exact[ev.note_id] = (
                    locked_onset,
                    locked_duration,
                    family,
                    f"{key[0]}:{key[1]}:{group_index}:locked",
                )
                out.append(
                    copy_event(
                        ev,
                        start_beat=float(locked_onset),
                        duration_beats=float(locked_duration),
                        role=role,
                        phrase_id=phrase,
                    )
                )
                continue
            overlaps = raw_next is not None and ev.start_beat + ev.duration_beats > raw_next + 0.04
            target_id, release_reason, pedal_source = release_by_id.get(
                ev.note_id, (None, None, None)
            )
            release_at = onset_by_id.get(target_id) if target_id else None
            duration = _duration(
                ev.duration_beats,
                onset,
                nxt,
                overlaps,
                family,
                preserve=(
                    local_settings.preserve_performed_durations()
                    or (
                        ev.source_backend == "midi"
                        and not local_settings.uses_improved_readable()
                    )
                ),
                measure_length=measure_length,
                beat_length=beat_length,
                release_reason=release_reason,
                settings=local_settings,
                release_at=release_at,
                local_pulse=prev_interval if family == "triplet" else None,
            )
            exact[ev.note_id] = (onset, duration, family, f"{key[0]}:{key[1]}:{group_index}")
            out.append(copy_event(ev, start_beat=float(onset), duration_beats=float(duration),
                                  role=role, phrase_id=phrase))
    raw_by_id = {e.note_id: e for e in raw}
    out, exact, phrase_duration_adjustments = _readable_phrase_unify_durations(
        out,
        exact,
        settings,
        raw_by_id,
        measure_length=measure_length,
        beat_length=beat_length,
    )
    out, exact, detached_adjustments = _readable_unify_detached_pulse(
        out,
        exact,
        settings,
        raw_by_id,
        measure_length=measure_length,
        beat_length=beat_length,
    )
    phrase_duration_adjustments.update(detached_adjustments)
    out, exact, chord_duration_adjustments = _readable_unify_chord_durations(
        out, exact, settings, measure_length=measure_length
    )
    out = _stable_lanes(out, exact, profile.grand_staff)
    out = _conservative_articulations(out, settings=settings)
    ornament_marks = _readable_mark_ornaments(
        out,
        onset_by_id,
        exact,
        roles,
        settings,
        raw_by_id,
        measure_length=measure_length,
    )
    if ornament_marks:
        tagged = []
        for ev in out:
            mark = ornament_marks.get(ev.note_id)
            if mark and not ev.articulation:
                tagged.append(copy_event(ev, articulation="ornament"))
            else:
                tagged.append(ev)
        out = tagged
    decisions, notes = [], []
    for ev in out:
        source = raw_by_id[ev.note_id]
        onset, duration, family, group_id = exact[ev.note_id]
        target_id, release_reason, pedal_source = release_by_id.get(
            ev.note_id, (None, None, None)
        )
        release_at = onset_by_id.get(target_id) if target_id else None
        error_beats = ev.start_beat - offset - source.start_beat
        bpm = _local_bpm(source, tempo_map)
        notes.append(ScoreNote(
            ev.note_id, onset, duration, ev.voice,
            staff_for_hand(ev.hand, ev.pitch) if profile.grand_staff else 0,
            ev.role, family, group_id,
            musical_voice=ev.musical_voice,
            voice_provenance=ev.voice_provenance or (
                "supplied" if source.voice_assigned else "inferred"
            ),
        ))
        reason = "bounded_voice_search"
        if ev.note_id in shared_beat_adjustments:
            reason = shared_beat_adjustments[ev.note_id].get("reason") or "readable_shared_beat"
        elif ev.note_id in phrase_duration_adjustments:
            reason = phrase_duration_adjustments[ev.note_id].get("reason") or "readable_phrase_duration"
        elif ev.note_id in chord_duration_adjustments:
            reason = "readable_chord_duration"
        decision = {
            "note_id": ev.note_id, "raw_start": source.start_beat,
            "source_track_id": source.source_track_id, "source_program": source.source_program,
            "raw_duration": source.duration_beats, "quantized_start": ev.start_beat,
            "quantized_duration": ev.duration_beats, "score_onset": str(onset),
            "score_duration": str(duration),
            "performed_duration": source.duration_beats,
            "written_duration": float(duration),
            "voice": ev.voice,
            "printed_voice": ev.voice,
            "musical_voice": ev.musical_voice,
            "voice_provenance": ev.voice_provenance or (
                "supplied" if source.voice_assigned else "inferred"
            ),
            "voice_assigned": bool(source.voice_assigned),
            "hand": ev.hand.value,
            "role": ev.role, "role_confidence": 0.4, "rhythm_family": family,
            "phrase_id": ev.phrase_id, "hand_confidence": ev.hand_confidence,
            "voice_confidence": ev.voice_confidence,
            "group_id": group_id, "reason": reason,
            "score_beat_offset": offset,
            "onset_error_beats": error_beats,
            "onset_error_ms": beats_to_ms(error_beats, bpm),
            "local_tempo_bpm": bpm,
            "max_onset_move_beats": float(config.max_onset_move),
            "max_onset_move_ms": beats_to_ms(config.max_onset_move, bpm),
            "layout_authority": getattr(source, "layout_authority", "") or layout.authority.value,
            "articulation": ev.articulation or None,
            "articulation_source": ev.articulation_source or (
                "supplied" if ev.articulation else ""
            ),
            "release_reason": release_reason,
            "release_target_id": target_id,
            "release_at": None if release_at is None else float(release_at),
            "pedal_source": pedal_source,
            "source_ids": [ev.note_id],
            "policy_exceptions": [
                row for row in policy_exceptions
                if abs(float(row.get("onset", 0)) - float(source.start_beat)) < 1e-6
            ],
        }
        if ev.note_id in shared_beat_adjustments:
            decision["shared_beat"] = shared_beat_adjustments[ev.note_id]
        if ev.note_id in phrase_duration_adjustments:
            decision["phrase_duration"] = phrase_duration_adjustments[ev.note_id]
        if ev.note_id in chord_duration_adjustments:
            decision["chord_duration"] = chord_duration_adjustments[ev.note_id]
        if ev.note_id in ornament_marks:
            decision["ornament"] = ornament_marks[ev.note_id]
        decisions.append(decision)
    summary = summarize_quantization(raw, out, decisions)
    if collapse_warning:
        summary["solo_collapse_warning"] = collapse_warning
    summary.update(engine="performance", voice_count=len({(n.staff, n.voice) for n in notes}),
                   role_method="contextual_line_hypothesis", role_confidence=0.4,
                   timing_representation="rational", source_notes=len(raw),
                   layout_source=layout_source,
                   layout_authority=layout.authority.value,
                   score_beat_offset=offset,
                   beat_origin_source="detected_downbeat" if downbeats else "file_origin",
                   max_onset_error_beats=max((abs(d["onset_error_beats"]) for d in decisions), default=0),
                   max_onset_error_ms=max((abs(d["onset_error_ms"]) for d in decisions), default=0),
                   notation_settings=settings.to_dict(),
                   notation_cache_key=settings.cache_key(),
                   algorithm_version=settings.algorithm_version,
                   policy_exceptions=list(policy_exceptions),
                   score_profile=profile.to_dict(),
                   voice_diagnostics=list(layout.diagnostics))
    return out, decisions, PerformanceReport(summary, tuple(notes), decisions)
