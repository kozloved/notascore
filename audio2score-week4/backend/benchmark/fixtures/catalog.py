"""Deterministic synthetic catalog. No copyrighted recordings."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NoteSpec:
    pitch: int
    start_beat: float
    duration_beats: float
    velocity: int = 80
    hand: str = "right"
    voice: int = 0
    role: str | None = None
    keep: bool = True


@dataclass
class CaseSpec:
    case_id: str
    category: str
    description: str
    tempo_bpm: int = 120
    time_signature: str = "4/4"
    key: str = "C"
    notes: list[NoteSpec] = field(default_factory=list)
    ci: bool = True
    voice_count_rh: int | None = None
    keep_all_octaves: bool = False
    notation_plan_required: bool = True
    check_hands: bool = True
    # STRICT_METER | METER_AMBIGUOUS | METER_NOT_EVALUATED
    meter_eval: str = "STRICT_METER"


def _n(pitch, start, dur, hand="right", voice=0, vel=80, role=None, keep=True) -> NoteSpec:
    return NoteSpec(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        velocity=vel,
        hand=hand,
        voice=voice,
        role=role,
        keep=keep,
    )


def _c_major_quarters() -> list[NoteSpec]:
    pitches = [60, 62, 64, 65, 67, 69, 71, 72]
    return [_n(p, float(i), 1.0, role="melody") for i, p in enumerate(pitches)]


def _g_major_eighths() -> list[NoteSpec]:
    pitches = [67, 69, 71, 72, 74, 76, 78, 79]
    return [_n(p, i * 0.5, 0.5, role="melody") for i, p in enumerate(pitches)]


def all_cases() -> list[CaseSpec]:
    return [
        CaseSpec(
            case_id="c_major_quarters",
            category="melody_simple",
            description="Monophonic C-major quarter-note scale, 4/4.",
            notes=_c_major_quarters(),
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="g_major_eighths",
            category="melody_simple",
            description="Monophonic G-major eighth notes, clear tempo.",
            notes=_g_major_eighths(),
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="melody_and_bass",
            category="piano_simple",
            description="Obvious RH melody over LH whole-note bass.",
            notes=[
                *[_n(p, float(i), 1.0, hand="right", role="melody") for i, p in enumerate([72, 74, 76, 77])],
                _n(48, 0.0, 4.0, hand="left", role="bass"),
            ],
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="c_major_block_chords",
            category="piano_chords",
            description="RH block triads with LH roots.",
            notes=[
                _n(60, 0.0, 1.0, voice=0),
                _n(64, 0.0, 1.0, voice=0),
                _n(67, 0.0, 1.0, voice=0),
                _n(67, 1.0, 1.0, voice=0),
                _n(71, 1.0, 1.0, voice=0),
                _n(74, 1.0, 1.0, voice=0),
                _n(69, 2.0, 1.0, voice=0),
                _n(72, 2.0, 1.0, voice=0),
                _n(76, 2.0, 1.0, voice=0),
                _n(65, 3.0, 1.0, voice=0),
                _n(69, 3.0, 1.0, voice=0),
                _n(72, 3.0, 1.0, voice=0),
                _n(48, 0.0, 1.0, hand="left", role="bass"),
                _n(43, 1.0, 1.0, hand="left", role="bass"),
                _n(45, 2.0, 1.0, hand="left", role="bass"),
                _n(41, 3.0, 1.0, hand="left", role="bass"),
            ],
            voice_count_rh=1,
            check_hands=True,
        ),
        CaseSpec(
            case_id="octave_doubling",
            category="piano_chords",
            description="Legitimate octave doubling; cleaner must not delete it.",
            notes=[
                _n(48, 0.0, 2.0, hand="left", vel=82, role="bass"),
                _n(60, 0.0, 2.0, hand="left", vel=80, role="bass"),
                _n(64, 0.0, 2.0, hand="right", vel=78),
                _n(67, 0.0, 2.0, hand="right", vel=76),
                _n(72, 2.0, 2.0, hand="right", vel=80, role="melody"),
                _n(84, 2.0, 2.0, hand="right", vel=78, role="melody"),
            ],
            keep_all_octaves=True,
            voice_count_rh=None,
            check_hands=False,
            meter_eval="METER_AMBIGUOUS",
        ),
        CaseSpec(
            case_id="two_hand_scale",
            category="piano_two_hands",
            description="Parallel diatonic scales two octaves apart.",
            notes=[
                spec
                for i in range(8)
                for spec in (
                    _n(48 + i, float(i), 0.5, hand="left", role="bass"),
                    _n(72 + i, float(i), 0.5, hand="right", role="melody"),
                )
            ],
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="middle_register",
            category="piano_two_hands",
            description="Two-hand piano with middle-register notes (55–67).",
            notes=[
                _n(36, 0.0, 2.0, hand="left", role="bass"),
                _n(43, 2.0, 2.0, hand="left", role="bass"),
                _n(55, 0.0, 1.0, hand="right", role="melody"),
                _n(57, 1.0, 1.0, hand="right", role="melody"),
                _n(60, 2.0, 1.0, hand="right", role="melody"),
                _n(64, 3.0, 1.0, hand="right", role="melody"),
                _n(67, 4.0, 1.0, hand="right", role="melody"),
                _n(36, 4.0, 2.0, hand="left", role="bass"),
            ],
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="hand_crossing",
            category="piano_two_hands",
            description="RH melody crosses below middle C; LH stays in the bass.",
            notes=[
                spec
                for i, (m, b) in enumerate(
                    zip([64, 62, 60, 59, 57, 55], [36, 38, 40, 41, 43, 45])
                )
                for spec in (
                    _n(b, float(i), 1.0, hand="left", role="bass"),
                    _n(m, float(i), 1.0, hand="right", role="melody"),
                )
            ],
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="polyphonic_rh",
            category="piano_two_hands",
            description="Sustained inner voice under an RH melody.",
            notes=[
                _n(60, 0.0, 4.0, hand="right", voice=1, role="accompaniment"),
                _n(76, 0.0, 1.0, hand="right", voice=0, role="melody"),
                _n(77, 1.0, 1.0, hand="right", voice=0, role="melody"),
                _n(79, 2.0, 1.0, hand="right", voice=0, role="melody"),
                _n(81, 3.0, 1.0, hand="right", voice=0, role="melody"),
                _n(48, 0.0, 4.0, hand="left", role="bass"),
            ],
            voice_count_rh=2,
            check_hands=False,
        ),
        CaseSpec(
            case_id="quarters",
            category="rhythm",
            description="Straight quarter notes in 4/4.",
            notes=[_n(72, float(i), 1.0) for i in range(8)],
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="eighths",
            category="rhythm",
            description="Straight eighth notes in 4/4.",
            notes=[_n(72, i * 0.5, 0.5) for i in range(16)],
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="sixteenths",
            category="rhythm",
            description="Straight sixteenth notes in 4/4.",
            notes=[_n(72, i * 0.25, 0.25) for i in range(16)],
            voice_count_rh=1,
            meter_eval="METER_NOT_EVALUATED",
        ),
        CaseSpec(
            case_id="dotted",
            category="rhythm",
            description="Dotted-quarter / eighth pairs.",
            notes=[
                _n(72, 0.0, 0.75),
                _n(74, 0.75, 0.25),
                _n(76, 1.0, 0.75),
                _n(77, 1.75, 0.25),
                _n(79, 2.0, 1.0),
                _n(81, 3.0, 1.0),
            ],
            voice_count_rh=1,
            meter_eval="METER_NOT_EVALUATED",
        ),
        CaseSpec(
            case_id="triplets",
            category="rhythm",
            description="Eighth-note triplets filling two beats, then quarters.",
            notes=[
                _n(72, 0.0, 1.0 / 3.0),
                _n(74, 1.0 / 3.0, 1.0 / 3.0),
                _n(76, 2.0 / 3.0, 1.0 / 3.0),
                _n(77, 1.0, 1.0 / 3.0),
                _n(79, 4.0 / 3.0, 1.0 / 3.0),
                _n(81, 5.0 / 3.0, 1.0 / 3.0),
                _n(83, 2.0, 1.0),
                _n(84, 3.0, 1.0),
            ],
            voice_count_rh=1,
            meter_eval="METER_AMBIGUOUS",
        ),
        CaseSpec(
            case_id="syncopation",
            category="rhythm",
            description="Off-beat half-note syncopation in 4/4.",
            notes=[
                _n(72, 0.0, 0.5),
                _n(74, 0.5, 1.0),
                _n(76, 1.5, 0.5),
                _n(77, 2.0, 1.0),
                _n(79, 3.0, 1.0),
            ],
            voice_count_rh=1,
            meter_eval="METER_AMBIGUOUS",
        ),
        CaseSpec(
            case_id="waltz_3_4",
            category="rhythm",
            description="Simple 3/4 melody with bass on the downbeat.",
            tempo_bpm=90,
            time_signature="3/4",
            notes=[
                _n(48, 0.0, 1.0, hand="left", role="bass"),
                _n(72, 0.0, 1.0),
                _n(74, 1.0, 1.0),
                _n(76, 2.0, 1.0),
                _n(48, 3.0, 1.0, hand="left", role="bass"),
                _n(77, 3.0, 1.0),
                _n(76, 4.0, 1.0),
                _n(74, 5.0, 1.0),
            ],
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="compound_6_8",
            category="rhythm",
            description="6/8 compound pulse: two groups of three eighths.",
            time_signature="6/8",
            notes=[
                spec
                for bar in range(2)
                for spec in (
                    _n(48, bar * 3.0 + 0.0, 1.5, hand="left", role="bass"),
                    _n(72, bar * 3.0 + 0.0, 0.5),
                    _n(74, bar * 3.0 + 0.5, 0.5),
                    _n(76, bar * 3.0 + 1.0, 0.5),
                    _n(48, bar * 3.0 + 1.5, 1.5, hand="left", role="bass"),
                    _n(77, bar * 3.0 + 1.5, 0.5),
                    _n(79, bar * 3.0 + 2.0, 0.5),
                    _n(81, bar * 3.0 + 2.5, 0.5),
                )
            ],
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="midi_rh_lh_tracks",
            category="midi_ingest",
            description="Direct MIDI ingest with named RH/LH tracks.",
            notes=[
                _n(72, 0.0, 0.5),
                _n(76, 0.0, 0.5),
                _n(48, 0.0, 2.0, hand="left", role="bass"),
            ],
            voice_count_rh=1,
            meter_eval="METER_AMBIGUOUS",
        ),
        CaseSpec(
            case_id="midi_3_4",
            category="midi_ingest",
            description="MIDI file with an explicit 3/4 time signature.",
            tempo_bpm=96,
            time_signature="3/4",
            notes=[
                _n(72, 0.0, 1.0),
                _n(74, 1.0, 1.0),
                _n(76, 2.0, 1.0),
                _n(48, 0.0, 3.0, hand="left", role="bass"),
            ],
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="midi_6_8",
            category="midi_ingest",
            description="MIDI file with an explicit 6/8 time signature.",
            time_signature="6/8",
            notes=[
                _n(60, 0.0, 0.5, hand="left", role="bass"),
                _n(72, 0.0, 0.5),
                _n(72, 0.5, 0.5),
                _n(72, 1.0, 0.5),
                _n(60, 1.5, 0.5, hand="left", role="bass"),
                _n(74, 1.5, 0.5),
                _n(74, 2.0, 0.5),
                _n(74, 2.5, 0.5),
            ],
            voice_count_rh=1,
        ),
        CaseSpec(
            case_id="midi_chords_and_melody",
            category="midi_ingest",
            description="MIDI chord plus independent melodic voice.",
            notes=[
                _n(60, 0.0, 1.0, voice=0),
                _n(64, 0.0, 1.0, voice=0),
                _n(67, 0.0, 1.0, voice=0),
                _n(76, 0.0, 1.0, voice=1, role="melody"),
                _n(77, 1.0, 1.0, voice=1, role="melody"),
                _n(79, 2.0, 1.0, voice=1, role="melody"),
                _n(81, 3.0, 1.0, voice=1, role="melody"),
                _n(48, 0.0, 4.0, hand="left", role="bass"),
            ],
            voice_count_rh=2,
            check_hands=False,
        ),
    ]
