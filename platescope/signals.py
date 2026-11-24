"""Local paper response and vertically connected pigment bands."""

from dataclasses import dataclass, field, replace

import numpy as np
from scipy.ndimage import gaussian_filter1d

from . import splitting

COLORS = ("red", "green", "blue")


@dataclass(frozen=True)
class LaneSignal:
    number: int
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
    lane: int = 0
    parent: int = 0
    part: int | None = None
    seeds: tuple | None = None
    suggestion: dict | None = None
    split: int | None = None
    mask: np.ndarray | None = field(default=None, repr=False, compare=False)
    start: int = 0
    stop: int = 0


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
    return LaneSignal(numbering, box, original, background, components, density, profile)


def intervals(active, min_height):
    limits = np.flatnonzero(np.diff(np.pad(active.astype(np.int8), 1)))
    return [(int(a), int(b)) for a, b in zip(limits[::2], limits[1::2]) if b - a >= min_height]


def tail_factor(profile, start, stop):
    center = start + int(np.argmax(profile[start:stop]))
    half = profile[center] * .5
    lower = next((i for i in range(center, stop) if profile[i] < half), None)
    upper = next((i for i in range(center, start - 1, -1) if profile[i] < half), None)
    return (lower - center) / (center - upper) if lower is not None and upper is not None else None


def suggestion(lane, assessment):
    """Payload the desk can show and adopt."""
    if assessment.verdict == "single" or not assessment.seeds:
        return None
    return {
        "verdict": assessment.verdict,
        "reason": assessment.reason,
        "lane": lane.number,
        "seeds": [[int(x), int(y)] for x, y in assessment.seeds],
        "ratio": None if assessment.ratio is None else round(float(assessment.ratio), 4),
        "weakness": None if assessment.weakness is None else round(float(assessment.weakness), 4),
    }


def measure(view, lane, start, stop, mask, part=None, seeds=None, note=None, split=None, whole=False):
    x0, y0, _, _ = lane.box
    cluster = lane.density[start:stop]
    rows, columns = np.nonzero(mask)
    weights = cluster[mask]
    amount = float(weights.sum(dtype=np.float64))
    lx = x0 + int(round(np.average(columns, weights=weights)))
    ly = y0 + start + int(round(np.average(rows, weights=weights)))
    box = (x0 + int(columns.min()), y0 + start + int(rows.min()),
           x0 + int(columns.max()), y0 + start + int(rows.max()))
    traces = tuple(float(value) for value in lane.components[start:stop][mask].sum(axis=0, dtype=np.float64))
    if whole:
        first, last = 0, stop - start
    else:
        first, last = int(rows.min()), int(rows.max()) + 1
    window = lane.profile[start + first:start + last]
    peak = float(window.max()) if len(window) else 0.
    tail = tail_factor(lane.profile, start + first, start + last)
    return Band(0, box, (lx, ly), view.rf(ly), peak,
                int(rows.size), amount, traces, tail,
                lane=lane.number, part=part, seeds=seeds, suggestion=note, split=split,
                mask=mask, start=start, stop=stop)


def adopted(settings, numbering):
    return [entry for entry in settings.get("splits", []) if entry.get("lane") == numbering]


def dividable(lane, start, stop, channel, selected, seeds):
    result = splitting.divide(lane, start, stop, channel, selected, seeds)
    if result is None:
        return None
    owners, snapped = result
    groups = [selected & (owners == owner) for owner in (0, 1)]
    if not all(group.any() for group in groups):
        return None
    return groups, snapped


def parts(lane, start, stop, channel, selected, settings, minimum):
    """Apply the first saved split whose two seeds still land on this band."""
    for index, entry in enumerate(adopted(settings, lane.number)):
        seeds = entry.get("seeds") or []
        if len(seeds) != 2:
            continue
        result = dividable(lane, start, stop, channel, selected, seeds)
        if result is None:
            continue
        groups, snapped = result
        counts = [int(group.sum()) for group in groups]
        if min(counts) < minimum:
            # Settings changed so one saved lobe no longer reaches a readable
            # size: the split no longer applies, the band stays whole.
            continue
        found = []
        for owner, group in enumerate(groups):
            rows = np.nonzero(group)[0]
            found.append((float(rows.mean()), group,
                          (int(snapped[owner].col) + lane.box[0],
                           int(snapped[owner].row) + lane.box[1] + start)))
        found.sort(key=lambda item: -item[0])
        return [(group, seed) for _, group, seed in found], index
    return None, None


def bands(view, lane, settings):
    cutoff = settings["cutoff"]
    channel = settings["channel"]
    regions = intervals(lane.profile >= cutoff, settings["min_height"])
    collected = []
    for start, stop in reversed(regions):
        cluster = lane.density[start:stop]
        selected = cluster >= cutoff * .4
        if not selected.any():
            continue
        groups, index = parts(lane, start, stop, channel, selected, settings,
                              max(6, settings["min_height"]))
        if groups is not None:
            for part, (mask, seed) in enumerate(groups, 1):
                collected.append(measure(view, lane, start, stop, mask, part=part,
                                         seeds=seed, split=index))
            continue
        note = suggestion(lane, splitting.assess(lane, start, stop, channel, cutoff,
                                                 settings["min_height"]))
        collected.append(measure(view, lane, start, stop, selected, note=note, whole=True))
    origin = {}
    for index, band in enumerate(collected, 1):
        if band.split is not None:
            origin.setdefault(band.split, index)
    return [replace(band, number=index,
                    parent=index if band.split is None else origin[band.split])
            for index, band in enumerate(collected, 1)]


def series(view, lane, found, limit=540):
    """Per-band rows of summed counted density, pointing at counted pixels."""
    x0, y0, _, _ = lane.box
    palette = ("#166958", "#ac5619", "#3f6ea8", "#7a4b9e", "#b07a12", "#2f7f73")
    budget = max(2, limit // max(len(found), 1))
    output = []
    for index, band in enumerate(found):
        row = np.nonzero(band.mask.any(axis=1))[0]
        if not len(row):
            continue
        take = row if len(row) <= budget else row[np.linspace(0, len(row) - 1, budget).round().astype(int)]
        take = np.unique(take)
        cluster = lane.density[band.start:band.stop]
        samples = []
        for offset in take:
            columns = np.flatnonzero(band.mask[offset])
            weights = cluster[offset, columns]
            if not len(columns) or weights.sum() <= 0:
                continue
            # The most coloured counted pixel of this row: clicking the curve
            # returns to a pixel that belongs to this group, also when the row
            # carries pixels of both groups.
            column = int(columns[int(np.argmax(weights))])
            y = band.start + int(offset)
            samples.append({"x": round(view.rf(y0 + y), 6),
                            "y": round(float(weights.sum(dtype=np.float64)), 6),
                            "at": [x0 + column, y0 + y]})
        label = f"带 {band.parent} 第 {band.part}/2 团" if band.part else f"带 {band.number}"
        output.append({"key": index + 1, "label": label, "band": band.parent,
                       "part": band.part, "color": palette[index % len(palette)],
                       "at": list(band.center), "samples": samples})
    return output
