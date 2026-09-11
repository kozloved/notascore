"""Render the deterministic notation comparison; optional dependency: verovio."""

import json, sys
from pathlib import Path
from mir.types import MusicalEvent, Hand, ScoreMeta
from mir.performance_score import assign_pipeline_layout
from mir.score_profile import score_profile
from mir.hand_separator import HandSeparator
from mir.voice_separator import VoiceSeparator
from notation_engine.plan import NotationPlanner
from notation_engine.writer import NotationWriter
from mir.models import PlannedNote, PlannedRest
import verovio

label, dest = sys.argv[1], Path(sys.argv[2])
dest.mkdir(parents=True, exist_ok=True)
notes = [MusicalEvent(pitch, i + 0.05, duration, note_id=f'{i}:{pitch}',
                     hand=Hand.RIGHT, hand_locked=True, velocity=80)
         for i in range(8) for pitch, duration in ((60, .93), (67, .99))]
notes += [MusicalEvent(p, i, 2, note_id=f'lh{i}', hand=Hand.LEFT,
                       hand_locked=True, velocity=80) for i,p in zip(range(0,8,2), [48,45,53,48])]
layout = assign_pipeline_layout(notes, score_profile(notes), HandSeparator(), VoiceSeparator())
writer = NotationWriter()
plan, _ = writer.planner.build(layout, meta=ScoreMeta(time_sig_hint='4/4', key_hint='C'), quantization_mode='performance')
plan.title = label
score = writer.score_from_plan(plan)
score.metadata.title = label.capitalize()
score.metadata.movementName = label.capitalize()
path = dest / f'{label}.musicxml'
writer._export_musicxml(score, path)
tk = verovio.toolkit()
tk.setOptions({'pageWidth':1800, 'pageHeight':1100, 'scale':45, 'adjustPageHeight':True, 'breaks':'auto'})
assert tk.loadFile(str(path))
(dest / f'{label}.svg').write_text(tk.renderToSVG(1))
elements=[e for m in plan.measures for s in m.staves for v in s.voices for e in v.elements]
metrics={'source_notes':len(notes), 'measures':len(plan.measures),
'notation_note_chord_symbols':sum(isinstance(e,PlannedNote) for e in elements),
'rests':sum(isinstance(e,PlannedRest) for e in elements),
'max_voices_per_staff':max(len(s.voices) for m in plan.measures for s in m.staves),
'micro_notes':sum(isinstance(e,PlannedNote) and e.duration_q < .25 for e in elements),
 'tied_symbols':sum(isinstance(e,PlannedNote) and bool(e.tie) for e in elements)}
(dest / f'{label}.json').write_text(json.dumps(metrics,indent=2)+'\n')
print(metrics)
