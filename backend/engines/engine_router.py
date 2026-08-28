from engines.basic_pitch_engine import BasicPitchEngine
from engines.mr_mt3_engine import MRMT3Engine

def get_engine(mode:str):
    return MRMT3Engine() if mode in ('quality', 'polyphonic', 'mt3') else BasicPitchEngine()
