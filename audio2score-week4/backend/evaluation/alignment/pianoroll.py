"""Piano-roll diagnostic images for Checkpoint 9B."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from mir.types import NoteEvent


def write_piano_roll(
    path: Path,
    *,
    reference: Sequence[NoteEvent],
    predicted: Sequence[NoteEvent],
    title: str,
) -> Path | None:
    """Write a simple reference-vs-prediction piano-roll PNG.

    Returns None if matplotlib is unavailable.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except Exception:
        return None

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 5))
    pitches = []
    for n in list(reference) + list(predicted):
        pitches.append(int(n.pitch))
    if not pitches:
        ax.set_title(title + " (empty)")
        fig.savefig(str(path), dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path

    ymin = min(pitches) - 2
    ymax = max(pitches) + 2

    for n in reference:
        start = float(n.start_time)
        dur = max(0.02, float(n.end_time) - start)
        ax.add_patch(
            Rectangle(
                (start, int(n.pitch) - 0.4),
                dur,
                0.8,
                facecolor="#1f77b4",
                edgecolor="#0b3d66",
                alpha=0.55,
                label="reference",
            )
        )
        ax.plot([start], [int(n.pitch)], "o", color="#0b3d66", markersize=3)

    for n in predicted:
        start = float(n.start_time)
        dur = max(0.02, float(n.end_time) - start)
        ax.add_patch(
            Rectangle(
                (start, int(n.pitch) - 0.35),
                dur,
                0.7,
                facecolor="#ff7f0e",
                edgecolor="#a34c00",
                alpha=0.45,
                label="predicted",
            )
        )
        ax.plot([start], [int(n.pitch)], "x", color="#a34c00", markersize=4)

    # Deduplicate legend entries
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    if by_label:
        ax.legend(by_label.values(), by_label.keys(), loc="upper right")

    ax.set_ylim(ymin, ymax)
    ax.set_xlabel("Time (seconds, absolute)")
    ax.set_ylabel("MIDI pitch")
    ax.set_title(title)
    ax.grid(True, alpha=0.25)
    # Autoscale x from data
    all_t = [float(n.start_time) for n in list(reference) + list(predicted)] + [
        float(n.end_time) for n in list(reference) + list(predicted)
    ]
    if all_t:
        ax.set_xlim(min(all_t) - 0.2, max(all_t) + 0.2)
    fig.savefig(str(path), dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path
