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


def pedal_spans(pedal_events) -> tuple[tuple[float, float], ...]:
    spans = []
    down_at = None
    for item in sorted(pedal_events or (), key=lambda row: float(row[0])):
        time_sec = float(item[0])
        value = int(item[1])
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


def _onset_candidates(raw, max_move, settings=None, exceptions=None):
    settings = _settings(settings)
    # An already representable attack is stronger evidence than a preference
    # for a simpler rhythm. In particular, preserve 64ths and offbeat triplets.
    exact_vocab, search_vocab = _onset_vocab(settings)
    for denominator, family in exact_vocab:
        exact = Fraction(round(raw * denominator), denominator)
        if abs(float(exact) - raw) <= min(1e-7, max_move):
            return [(exact, family, 0.0)]
    # Exact values outside the selected grid still win: they are distinct attacks.
    # Triplet policy is still honored; a required tuplet is a recorded exception.
    if not settings.uses_current_vocabulary():
        fallback_exact = _ONSET_EXACT
        if settings.triplet_policy == TripletPolicy.DISABLED:
            fallback_exact = [(d, f) for d, f in _ONSET_EXACT if f != "triplet"]
        for denominator, family in fallback_exact:
            exact = Fraction(round(raw * denominator), denominator)
            if abs(float(exact) - raw) <= min(1e-7, max_move):
                return [(exact, family, 0.0)]
    candidates = {}
    literal = settings.interpretation == Interpretation.LITERAL

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
    if release_reason == "pedal_tail":
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


def _release_decisions(events, *, settings=None, pedal=None):
    """Map note_id -> (release_target_id_or_None, reason, pedal_source)."""
    by_hand = defaultdict(list)
    for ev in events:
        by_hand[ev.hand].append(ev)
    decisions = {}
    for group in by_hand.values():
        ordered = sorted(group, key=lambda e: (e.start_beat, e.pitch, e.note_id))
        for ev in ordered:
            decisions[ev.note_id] = _release_hypothesis(
                ev, ordered, settings=settings, pedal=pedal
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
        exact = min(named, key=lambda d: abs(float(d) - raw))
        if abs(float(exact) - raw) < 1e-7:
            return exact
    # Preserve-overlap wins over an inferred pedal-tail cutoff.
    if (
        settings.overlap_handling != OverlapHandling.PRESERVE
        and release_reason == "pedal_tail"
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


def _readable_v2_fill_small_release_gap(
    raw,
    onset,
    next_onset,
    to_bar,
    *,
    release_reason,
    settings,
):
    """Opt-in readable-v2: leftover gaps smaller than a sixteenth are articulation.

    Case A (detached quarters with ~80ms releases) should be written as quarters.
    Case B (short notes plus a visible rest through the beat) must keep the rest.
    Independent holds are left alone. This never extends a note past the next
    attack or past the barline, and it does not run on the default engine.
    """
    if not settings.uses_improved_readable():
        return None
    if release_reason in {
        "independent_hold",
        "multi_attack_hold",
        "overlapping_repeat",
        "pedal_tail",
    }:
        return None
    sixteenth = 0.25
    if next_onset is not None:
        ioi = Fraction(next_onset) - Fraction(onset)
        remaining = float(ioi) - float(raw)
        if ioi > 0 and 0 <= remaining < sixteenth:
            return ioi
    if to_bar is not None and Fraction(to_bar) > 0:
        remaining = float(to_bar) - float(raw)
        if 0 <= remaining < sixteenth:
            return Fraction(to_bar)
    return None


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
            # Pulse re-attack under pedal is a line continuation.
            if (
                0.20 <= gap <= 2.05
                and gap * 1.25 < raw < gap * 4.0
                and _pulsed_line_evidence(ev, nxt, ordered_same_hand)
            ):
                source = "cc64" if nxt_pedal else "hypothesis"
                return nxt.note_id, "pedal_tail", source
            # Near-simultaneous or independently sustained repeated pitch.
            if gap <= 0.12 or raw >= gap * 4.0:
                return None, "overlapping_repeat", None
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
    by_hand = defaultdict(list)
    for ev in events:
        by_hand[ev.hand].append(ev)
    capped = {}
    for group in by_hand.values():
        ordered = sorted(group, key=lambda e: (e.start_beat, e.pitch, e.note_id))
        for ev in ordered:
            target_id, _reason, _source = _release_hypothesis(ev, ordered)
            if target_id is None or target_id not in by_id:
                capped[ev.note_id] = ev
            else:
                gap = float(by_id[target_id].start_beat - ev.start_beat)
                capped[ev.note_id] = copy_event(ev, duration_beats=gap)
    return [capped.get(ev.note_id, ev) for ev in events]


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
    return LayoutResult(
        events=out,
        authority=authority,
        voice_complete=True,
        hand_complete=hands_complete(out) if profile.grand_staff else True,
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
        events = stamp_authority(_score_voices(cleared, VoiceSeparator()), LayoutAuthority.INFERRED)
        return LayoutResult(events, LayoutAuthority.INFERRED, True, True)

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

    events = stamp_authority(
        _score_voices(HandSeparator().separate(raw), VoiceSeparator()),
        LayoutAuthority.INFERRED,
    )
    return LayoutResult(events, LayoutAuthority.INFERRED, True, True)


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
    spans = pedal_spans(pedal_events)

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
    release_by_id = _release_decisions(interpreted, settings=settings, pedal=spans)
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
            for ev in group:
                onset_by_id[ev.note_id] = onset
            onset_jobs.append((key, group, onset, family, nxt, raw_next, i))

    out, exact = [], {}
    for key, group, onset, family, nxt, raw_next, group_index in onset_jobs:
        bar_number = int(onset / measure_length) + 1 if measure_length > 0 else 1
        local_settings = settings.resolved_for_measure(bar_number)
        for ev in group:
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
                preserve=ev.source_backend == "midi",
                measure_length=measure_length,
                beat_length=beat_length,
                release_reason=release_reason,
                release_at=release_at,
                settings=local_settings,
            )
            exact[ev.note_id] = (onset, duration, family, f"{key[0]}:{key[1]}:{group_index}")
            role, phrase = roles[ev.note_id]
            out.append(copy_event(ev, start_beat=float(onset), duration_beats=float(duration),
                                  role=role, phrase_id=phrase))
    out = _stable_lanes(out, exact, profile.grand_staff)
    raw_by_id = {e.note_id: e for e in raw}
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
        decisions.append({
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
            "group_id": group_id, "reason": "bounded_voice_search",
            "score_beat_offset": offset,
            "onset_error_beats": error_beats,
            "onset_error_ms": beats_to_ms(error_beats, bpm),
            "local_tempo_bpm": bpm,
            "max_onset_move_beats": float(config.max_onset_move),
            "max_onset_move_ms": beats_to_ms(config.max_onset_move, bpm),
            "layout_authority": getattr(source, "layout_authority", "") or layout.authority.value,
            "release_reason": release_reason,
            "release_target_id": target_id,
            "release_at": None if release_at is None else float(release_at),
            "pedal_source": pedal_source,
            "source_ids": [ev.note_id],
            "policy_exceptions": [
                row for row in policy_exceptions
                if abs(float(row.get("onset", 0)) - float(source.start_beat)) < 1e-6
            ],
        })
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
                   score_profile=profile.to_dict())
    return out, decisions, PerformanceReport(summary, tuple(notes), decisions)
