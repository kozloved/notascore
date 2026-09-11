from transcription_fed.reconcile import reconcile_transcriptions
from mir.types import NoteEvent


def _n(pitch, start, end, *, backend="mt3", conf=0.9, ident=""):
    return NoteEvent(
        pitch=pitch,
        start_time=start,
        end_time=end,
        velocity=80,
        confidence=conf,
        note_id=ident,
        source_backend=backend,
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


def test_specialist_can_win_timing_when_confident():
    global_notes = [_n(60, 1.018, 1.5, ident="g")]
    specialist = [_n(60, 1.011, 1.5, backend="transkun", conf=0.9, ident="s")]
    result = reconcile_transcriptions(global_notes, specialist)
    assert abs(result.notes[0].start_time - 1.011) < 1e-9
    assert result.fused[0].canonical_backend == "transkun"
    assert [e.backend for e in result.fused[0].evidence] == ["mt3", "transkun"]
