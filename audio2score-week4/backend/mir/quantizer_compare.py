"""Side-by-side comparison of production vs experimental quantizers.

Does not change product behavior. Adaptive / PM2S / identity / strict-grid
are run only when this module is invoked explicitly.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from mir.models import MeterHypothesis
from mir.pipeline_config import QuantizationMode
from mir.quantizer import MeasureQuantizer
from mir.types import MusicalEvent


EXPERIMENTAL_MODES = (
    QuantizationMode.ADAPTIVE,
    QuantizationMode.STRICT_GRID,
    QuantizationMode.OFF,
    QuantizationMode.PM2S,
)


def compare_quantizers(
    events: Sequence[MusicalEvent],
    meter: MeterHypothesis,
    *,
    experimental_modes: Iterable[QuantizationMode | str] | None = None,
    config=None,
) -> dict:
    """Run the production engine and requested experimental engines.

    Returns a JSON-serializable report. Never selects an experimental engine
    as the product result.
    """
    production = MeasureQuantizer(config=config).quantize_production(list(events), meter)
    report = {
        "production": production.to_dict(),
        "experimental": {},
        "production_engine": "performance",
    }
    modes = list(experimental_modes) if experimental_modes is not None else list(EXPERIMENTAL_MODES)
    for mode in modes:
        experimental = MeasureQuantizer(config=config, mode=mode).quantize_experimental(
            list(events), meter, mode
        )
        key = experimental.mode
        report["experimental"][key] = experimental.to_dict()
    return report
