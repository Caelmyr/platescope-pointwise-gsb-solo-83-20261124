"""Local paper response and vertically connected pigment bands."""

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d

COLORS = ("red", "green", "blue")


@dataclass(frozen=True)
class LaneSignal:
    box: tuple
    original: np.ndarray
    background: np.ndarray
    components: np.ndarray
    density: np.ndarray
    profile: np.ndarray


@dataclass(frozen=True)
class Band:
    number: int
    box: tuple
    center: tuple
    rf: float
    peak: float
    pixels: int
    amount: float
    components: tuple
    tail: float | None


def scan(view, numbering, channel):
    box = view.lane_box(numbering)
    original = view.lane_values(numbering)
    if original.ndim == 2:
        original = original[:, :, None]
    height, width = original.shape[:2]
    # Background is a per-channel lane constant. This normal path assumes
    # most of a lane is clean and lighting varies little within it.
    stride = max(1, height * width // 60_000)
    background = np.quantile(original.reshape(-1, original.shape[2])[::stride], .8, axis=0)
    components = np.clip(1 - original / np.maximum(background, .02), 0, 1).astype(np.float32)
    if channel == "auto":
        density = components.max(axis=2)
    else:
        density = components[:, :, min(components.shape[2] - 1, COLORS.index(channel))]
    # Give lane edges less weight against plate-border marks and nearby lanes.
    inset = min((width - 1) // 2, width // 9)
    core = density[:, inset:width - inset]
    profile = gaussian_filter1d(core.mean(axis=1), sigma=1.3, mode="nearest")
    return LaneSignal(box, original, background, components, density, profile)


def intervals(active, min_height):
    limits = np.flatnonzero(np.diff(np.pad(active.astype(np.int8), 1)))
    return [(int(a), int(b)) for a, b in zip(limits[::2], limits[1::2]) if b - a >= min_height]


def tail_factor(profile, start, stop):
    center = start + int(np.argmax(profile[start:stop]))
    half = profile[center] * .5
    lower = next((i for i in range(center, stop) if profile[i] < half), None)
    upper = next((i for i in range(center, start - 1, -1) if profile[i] < half), None)
    return (lower - center) / (center - upper) if lower is not None and upper is not None else None


def bands(view, lane, settings):
    x0, y0, _, _ = lane.box
    regions = intervals(lane.profile >= settings["cutoff"], settings["min_height"])
    result = []
    for number, (start, stop) in enumerate(reversed(regions), 1):
        cluster = lane.density[start:stop]
        selected = cluster >= settings["cutoff"] * .4
        rows, columns = np.nonzero(selected)
        if not rows.size:
            continue
        weights = cluster[selected]
        amount = float(weights.sum(dtype=np.float64))
        lx = x0 + int(round(np.average(columns, weights=weights)))
        ly = y0 + start + int(round(np.average(rows, weights=weights)))
        box = (x0 + int(columns.min()), y0 + start + int(rows.min()),
               x0 + int(columns.max()), y0 + start + int(rows.max()))
        traces = tuple(float(value) for value in lane.components[start:stop][selected].sum(axis=0, dtype=np.float64))
        result.append(Band(number, box, (lx, ly), view.rf(ly), float(lane.profile[start:stop].max()),
                           int(rows.size), amount, traces, tail_factor(lane.profile, start, stop)))
    return result
