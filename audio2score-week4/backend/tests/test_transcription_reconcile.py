from transcription_fed.reconcile import reconcile_transcriptions
from mir.types import InstrumentKind, NoteEvent


def _n(pitch, start, end, *, backend="mt3", conf=0.9, ident="", instrument=InstrumentKind.UNKNOWN, stem=""):
    return NoteEvent(
        pitch=pitch,
        start_time=start,
        end_time=end,
        velocity=80,
        confidence=conf,
        note_id=ident,
        source_backend=backend,
        instrument=instrument,
        source_track_id=stem,
    )


def test_matching_chord_does_not_duplicate():
    global_notes = [
        _n(60, 1.018, 1.4, ident="gC"),
        _n(64, 1.021, 1.4, ident="gE"),
        _n(67, 1.020, 1.4, ident="gG"),
    ]
    specialist = [
        _n(60, 1.011, 1.39, backend="transkun", conf=0.8, ident="sC"),
        _n(64, 1.015, 1.39, backend="transkun", conf=0.8, ident="sE"),
        _n(67, 1.013, 1.39, backend="transkun", conf=0.8, ident="sG"),
    ]
    result = reconcile_transcriptions(global_notes, specialist)
    assert len(result.notes) == 3
    assert all(len(item.evidence) == 2 for item in result.fused)
    assert {n.pitch for n in result.notes} == {60, 64, 67}


def test_full_mix_protects_against_separation_loss():
    global_notes = [_n(72, 0.5, 1.0, ident="keep"), _n(60, 0.0, 0.4, ident="lost-in-stem")]
    specialist = [_n(72, 0.51, 1.0, backend="transkun", conf=0.9, ident="s")]
    result = reconcile_transcriptions(global_notes, specialist)
    assert len(result.notes) == 2
    assert any(n.note_id == "lost-in-stem" for n in result.unmatched_global)


def test_weak_stem_ghost_is_dropped():
    global_notes = [_n(60, 0.0, 0.5, ident="real")]
    ghost = [_n(61, 0.02, 0.2, backend="transkun", conf=0.1, ident="ghost")]
    result = reconcile_transcriptions(global_notes, ghost)
    assert len(result.notes) == 1
    assert result.notes[0].pitch == 60
    assert result.dropped_ghosts[0].note_id == "ghost"
    assert result.diagnostics["dropped_ghosts"][0]["note_id"] == "ghost"


def test_duration_similarity_breaks_equal_onset_ties():
    global_notes = [_n(60, 1.0, 2.0, ident="held")]
    specialist = [
        _n(60, 1.02, 1.2, backend="transkun", conf=0.4, ident="short"),
        _n(60, 1.02, 2.02, backend="transkun", conf=0.4, ident="long"),
    ]
    result = reconcile_transcriptions(global_notes, specialist)
    assert len(result.notes) == 1
    spec = next(e for e in result.fused[0].evidence if e.backend == "transkun")
    assert abs(spec.offset_sec - 2.02) < 1e-9


def test_matching_keeps_mt3_timing():
    global_notes = [_n(60, 1.018, 1.5, ident="g")]
    specialist = [_n(60, 1.011, 1.5, backend="transkun", conf=0.9, ident="s")]
    result = reconcile_transcriptions(global_notes, specialist)
    assert abs(result.notes[0].start_time - 1.018) < 1e-9
    assert result.fused[0].canonical_backend == "mt3"
    assert [e.backend for e in result.fused[0].evidence] == ["mt3", "transkun"]
    assert len(result.fused[0].evidence) == 2


def test_a_mt3_and_piano_stem_same_note():
    mix = [_n(60, 1.000, 1.4, ident="mixC")]
    piano = [_n(60, 1.012, 1.39, backend="basic_pitch", conf=0.85, ident="pC", instrument=InstrumentKind.PIANO, stem="piano")]
    result = reconcile_transcriptions(mix, piano, specialist_backend="basic_pitch")
    assert len(result.notes) == 1
    assert len(result.fused[0].evidence) == 2
    assert abs(result.notes[0].start_time - 1.000) < 1e-9
    assert result.fused[0].instrument == "piano"


def test_b_mt3_only_event_is_kept():
    mix = [_n(64, 2.0, 2.4, ident="only")]
    result = reconcile_transcriptions(mix, [])
    assert len(result.notes) == 1
    assert result.notes[0].note_id == "only"
    assert result.unmatched_global[0].note_id == "only"


def test_c_high_confidence_stem_only_becomes_candidate():
    mix = [_n(60, 0.0, 0.4, ident="mix")]
    extra = [_n(67, 1.0, 1.3, backend="basic_pitch", conf=0.9, ident="stem-only", instrument=InstrumentKind.GUITAR, stem="guitar")]
    result = reconcile_transcriptions(mix, extra, specialist_backend="basic_pitch")
    assert len(result.notes) == 2
    assert any(n.note_id == "stem-only" for n in result.unmatched_specialist)


def test_d_weak_stem_ghost_debug_only():
    mix = [_n(60, 0.0, 0.4, ident="mix")]
    ghost = [_n(61, 0.5, 0.7, backend="basic_pitch", conf=0.2, ident="ghost", instrument=InstrumentKind.PIANO, stem="piano")]
    result = reconcile_transcriptions(mix, ghost, specialist_backend="basic_pitch")
    assert all(n.note_id != "ghost" for n in result.notes)
    assert result.dropped_ghosts[0].note_id == "ghost"
    assert any(row["note_id"] == "ghost" for row in result.diagnostics["dropped_ghosts"])


def test_e_same_pitch_different_instruments_stay_two_notes():
    mix = []
    stems = [
        _n(60, 1.0, 1.4, backend="basic_pitch", conf=0.9, ident="pianoC", instrument=InstrumentKind.PIANO, stem="piano"),
        _n(60, 1.0, 1.4, backend="basic_pitch", conf=0.9, ident="bassC", instrument=InstrumentKind.BASS, stem="bass"),
    ]
    result = reconcile_transcriptions(mix, stems, specialist_backend="basic_pitch")
    assert len(result.notes) == 2
    assert {n.instrument for n in result.notes} == {InstrumentKind.PIANO, InstrumentKind.BASS}


def test_e_mt3_unlabeled_does_not_merge_piano_and_bass():
    mix = [_n(60, 1.0, 1.4, ident="mixC")]
    stems = [
        _n(60, 1.008, 1.4, backend="basic_pitch", conf=0.9, ident="pianoC", instrument=InstrumentKind.PIANO, stem="piano"),
        _n(60, 1.006, 1.4, backend="basic_pitch", conf=0.9, ident="bassC", instrument=InstrumentKind.BASS, stem="bass"),
    ]
    result = reconcile_transcriptions(mix, stems, specialist_backend="basic_pitch")
    assert len(result.notes) == 2
    instruments = {item.instrument for item in result.fused}
    assert "piano" in instruments
    assert "bass" in instruments


def test_f_chord_from_both_systems_is_three_notes():
    mix = [
        _n(60, 1.0, 1.4, ident="c"),
        _n(64, 1.0, 1.4, ident="e"),
        _n(67, 1.0, 1.4, ident="g"),
    ]
    piano = [
        _n(60, 1.01, 1.4, backend="basic_pitch", conf=0.8, ident="pc", instrument=InstrumentKind.PIANO, stem="piano"),
        _n(64, 1.01, 1.4, backend="basic_pitch", conf=0.8, ident="pe", instrument=InstrumentKind.PIANO, stem="piano"),
        _n(67, 1.01, 1.4, backend="basic_pitch", conf=0.8, ident="pg", instrument=InstrumentKind.PIANO, stem="piano"),
    ]
    result = reconcile_transcriptions(mix, piano, specialist_backend="basic_pitch")
    assert len(result.notes) == 3
    assert {n.pitch for n in result.notes} == {60, 64, 67}


def test_g_repeated_same_pitch_attacks_are_not_merged():
    mix = [
        _n(60, 1.000, 1.20, ident="a1"),
        _n(60, 1.090, 1.28, ident="a2"),
    ]
    piano = [
        _n(60, 1.005, 1.20, backend="basic_pitch", conf=0.9, ident="p1", instrument=InstrumentKind.PIANO, stem="piano"),
        _n(60, 1.095, 1.28, backend="basic_pitch", conf=0.9, ident="p2", instrument=InstrumentKind.PIANO, stem="piano"),
    ]
    result = reconcile_transcriptions(mix, piano, specialist_backend="basic_pitch")
    assert len(result.notes) == 2
    onsets = sorted(n.start_time for n in result.notes)
    assert abs(onsets[0] - 1.000) < 1e-9
    assert abs(onsets[1] - 1.090) < 1e-9
