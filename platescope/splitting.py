"""Adoptable split of one band into two lobes joined by a faint tail.

The decision works on optical density, not on the clipped display density: a
shallow neck between two pigmented lobes can survive while the display value
of both lobes is saturated.  Two lobe seeds are found on a smoothed density
field, the highest-possible lowest point of a path between them is measured,
and the counted pixels are divided by a density watershed from the two seeds.
The watershed follows the ridge that separates the lobes: it is neither a
straight cut across the faintest row nor an assignment of the whole diagonal
tail to one side.
"""

from dataclasses import dataclass
from heapq import heappop, heappush

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter

COLORS = ("red", "green", "blue")
EPSILON = 1e-3
CLIPPED = 5.0            # optical density of a near-black pixel
CLIP_FRACTION = .15      # share of clipped pixels that makes a channel unusable
SADDLE_LIMIT = .65       # valley must fall at least 35% below the weaker lobe
WEAK_LIMIT = .35         # a second lobe must reach 35% of the stronger lobe
SMOOTH = 1.2


@dataclass(frozen=True)
class Peak:
    value: float
    row: int
    col: int


@dataclass(frozen=True)
class Ridge:
    value: float
    row: int
    col: int
    fraction: float          # position of the low point along the ridge path


@dataclass(frozen=True)
class Assessment:
    verdict: str             # split / undulation / weak / close / small / single
    seeds: tuple = ()        # original-image ((x, y), (x, y)), only when two lobes were seen
    saddle: tuple | None = None
    ratio: float | None = None       # saddle / weaker peak
    weakness: float | None = None    # weaker peak / stronger peak
    fraction: float | None = None    # saddle position from the stronger peak
    reason: str = ""


def _channel_od(lane, start, stop, index):
    pixels = np.maximum(lane.original[start:stop, :, index].astype(np.float32), EPSILON)
    background = max(float(np.asarray(lane.background)[index]), .02)
    return np.clip(-np.log(pixels / background), 0, None)


def optical_density(lane, start, stop, channel, selected=None):
    """Unsaturated ink response relative to the lane background.

    With the automatic channel, the channel carrying the most ink is used.
    A channel clipped over much of the counted band is skipped when another
    channel still holds the faint neck, because a saturated neck would read
    as high as the lobes and hide the split.
    """
    if channel != "auto":
        return _channel_od(lane, start, stop, min(lane.original.shape[2] - 1, COLORS.index(channel)))
    masks = selected if selected is not None else np.ones(lane.density[start:stop].shape, dtype=bool)
    options = []
    for index in range(lane.original.shape[2]):
        values = _channel_od(lane, start, stop, index)
        signal = float(np.quantile(values[masks], .9)) if masks.any() else 0.
        clipped = float((values[masks] >= CLIPPED).mean()) if masks.any() else 1.
        options.append((round(clipped, 2) > CLIP_FRACTION, -round(signal, 2), index, values))
    return min(options, key=lambda item: item[:3])[3]


def field(lane, start, stop, channel, selected=None):
    return gaussian_filter(optical_density(lane, start, stop, channel, selected), SMOOTH, mode="nearest")


def _separation(min_height):
    # Two lobes closer than this would not survive the minimum band height.
    return max(6.0, float(min_height) * 1.2)


def _origin(lane, start, seed):
    """Convert a lane-local (row, column) to original-image (x, y)."""
    x0, y0, _, _ = lane.box
    return (x0 + int(seed.col), y0 + int(start) + int(seed.row))


def reason_for_split(ridge, ratio, weakness, pixels):
    side = "窄带一侧" if ridge.fraction < .5 else "宽带一侧"
    return (
        f"两块显色各自成峰，峰间最浅处只有较弱峰的 {ratio:.0%}，弱峰也达到主峰的 "
        f"{weakness:.0%}，是真实的第二团。切口沿两峰之间的密度脊线（分水岭）走，"
        f"不按最淡的一行横切，因此窄带连着的斜拖尾不会被削掉；也不把整条斜拖尾"
        f"并给一侧，两团之间的淡色按像素归属分开。原带计入的 {pixels} 个像素全部"
        f"保留，每个像素只归一团。分界最浅处略偏{side}。")


def _peaks(smooth, selected, min_height):
    if not selected.any():
        return []
    floor = max(.04, float(smooth[selected].max()) * .10)
    local = smooth >= maximum_filter(smooth, size=5, mode="nearest") - 1e-6
    rows, cols = np.nonzero(selected & local & (smooth >= floor))
    found = sorted((Peak(float(smooth[row, col]), int(row), int(col))
                    for row, col in zip(rows, cols)), key=lambda peak: -peak.value)
    separation = _separation(min_height)
    peaks = []
    for peak in found:
        if all((peak.row - other.row) ** 2 + (peak.col - other.col) ** 2 >= separation ** 2
               for other in peaks):
            peaks.append(peak)
        if len(peaks) >= 6:
            break
    return peaks


def ridge_path(smooth, selected, first, second):
    """Maximin path: keep as high as possible on the way between the seeds."""
    height, width = smooth.shape
    best = np.full((height, width), -np.inf, dtype=np.float32)
    parent = np.full((height, width), -1, dtype=np.int32)
    start = first.row * width + first.col
    target = second.row * width + second.col
    best[first.row, first.col] = smooth[first.row, first.col]
    heap = [(-float(smooth[first.row, first.col]), first.row, first.col)]
    visited = np.zeros((height, width), dtype=bool)
    while heap:
        neg, row, col = heappop(heap)
        if visited[row, col]:
            continue
        visited[row, col] = True
        if row * width + col == target:
            break
        value = -neg
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            rr, cc = row + dr, col + dc
            if not (0 <= rr < height and 0 <= cc < width):
                continue
            if not selected[rr, cc] or visited[rr, cc]:
                continue
            reached = min(value, float(smooth[rr, cc]))
            if reached > best[rr, cc] + 1e-9:
                best[rr, cc] = reached
                parent[rr, cc] = row * width + col
                heappush(heap, (-reached, rr, cc))
    if not np.isfinite(best[second.row, second.col]):
        return None
    path = []
    index = target
    seen = set()
    while index >= 0 and index not in seen:
        seen.add(index)
        row, col = divmod(index, width)
        path.append((row, col))
        if index == start:
            break
        index = int(parent[row, col])
    if not path or path[-1] != (first.row, first.col):
        return None
    path.reverse()
    values = [float(smooth[row, col]) for row, col in path]
    low = int(np.argmin(values))
    fraction = low / max(len(path) - 1, 1)
    return Ridge(values[low], path[low][0], path[low][1], fraction)


def watershed(smooth, selected, seeds):
    """Priority flood from the seeds; every counted pixel gets one owner."""
    height, width = smooth.shape
    owners = np.full((height, width), -1, dtype=np.int8)
    heap = []
    for owner, seed in enumerate(seeds):
        if not (0 <= seed.row < height and 0 <= seed.col < width):
            continue
        if not selected[seed.row, seed.col]:
            continue
        owners[seed.row, seed.col] = owner
        heappush(heap, (-float(smooth[seed.row, seed.col]), seed.row, seed.col, owner))
    while heap:
        neg, row, col, owner = heappop(heap)
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            rr, cc = row + dr, col + dc
            if not (0 <= rr < height and 0 <= cc < width):
                continue
            if not selected[rr, cc] or owners[rr, cc] >= 0:
                continue
            owners[rr, cc] = owner
            heappush(heap, (-float(smooth[rr, cc]), rr, cc, owner))
    # Counted islands that no flood reached still belong to the band.  Give
    # them to the nearest seed so the original pixel count is preserved.
    left = selected & (owners < 0)
    if left.any():
        rows, cols = np.nonzero(left)
        distances = np.stack([(rows - seed.row) ** 2 + (cols - seed.col) ** 2 for seed in seeds])
        owners[rows, cols] = np.argmin(distances, axis=0).astype(np.int8)
    return owners


def snap(selected, row, col, radius=4):
    """Move a saved seed onto the nearest counted pixel."""
    height, width = selected.shape
    if not (0 <= row < height and 0 <= col < width):
        return None
    if selected[row, col]:
        return Peak(0., int(row), int(col))
    best = None
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            rr, cc = row + dr, col + dc
            if not (0 <= rr < height and 0 <= cc < width) or not selected[rr, cc]:
                continue
            distance = dr * dr + dc * dc
            if best is None or distance < best[0]:
                best = (distance, Peak(0., int(rr), int(cc)))
    return best[1] if best else None


def divide(lane, start, stop, channel, selected, seeds):
    """Partition counted pixels from two saved seeds in original-image (x, y)."""
    smooth = field(lane, start, stop, channel, selected)
    x0, y0, _, _ = lane.box
    snapped = []
    for x, y in seeds:
        row = int(y) - y0 - start
        col = int(x) - x0
        if not 0 <= row < stop - start:
            return None
        snapped.append(snap(selected, row, col))
    if any(seed is None for seed in snapped) or snapped[0] == snapped[1]:
        return None
    owners = watershed(smooth, selected, snapped)
    if not (owners == 0).any() or not (owners == 1).any():
        return None
    return owners, tuple(snapped)


def assess(lane, start, stop, channel, cutoff, min_height):
    """Decide whether one counted band really holds two pigment lobes."""
    cluster = lane.density[start:stop]
    selected = cluster >= cutoff * .4
    pixels = int(selected.sum())
    if pixels < max(6, min_height):
        return Assessment("small", reason="这块显色太小，未细分。")
    if pixels < 2 * max(6, min_height):
        return Assessment("small", reason="这块显色不足以拆成两团，保留整带。")
    smooth = field(lane, start, stop, channel)
    peaks = _peaks(smooth, selected, min_height)
    if len(peaks) < 2:
        return Assessment("single", reason="这块显色只有一个峰，看不出第二团，保留整带。")
    stronger = peaks[0]
    separation = _separation(min_height)
    weaker = next((peak for peak in peaks[1:]
                   if (peak.row - stronger.row) ** 2 + (peak.col - stronger.col) ** 2 >= separation ** 2),
                  None)
    if weaker is None:
        return Assessment("single", reason="这块显色只有一个峰，看不出第二团，保留整带。")
    pair = tuple(sorted((_origin(lane, start, stronger), _origin(lane, start, weaker))))
    if weaker.value < stronger.value * WEAK_LIMIT:
        return Assessment(
            "weak", seeds=pair,
            weakness=weaker.value / max(stronger.value, 1e-9),
            reason=(f"第二处起伏只有主峰的 {weaker.value / max(stronger.value, 1e-9):.0%}，"
                    "还看不出独立的一团，保留整带。"))
    ridge = ridge_path(smooth, selected, stronger, weaker)
    if ridge is None:
        return Assessment("single", reason="两处起伏之间没有可信的连通路径，保留整带。")
    ratio = ridge.value / max(weaker.value, 1e-9)
    if ratio > SADDLE_LIMIT:
        return Assessment(
            "undulation", seeds=pair,
            saddle=_origin(lane, start, ridge), ratio=ratio,
            weakness=weaker.value / max(stronger.value, 1e-9), fraction=ridge.fraction,
            reason=(f"两处起伏之间最浅处仍有较弱峰的 {ratio:.0%}，只是淡淡起伏，"
                    "未见清晰的第二团，保留整带。"))
    seeds = ((stronger.row, stronger.col), (weaker.row, weaker.col))
    owners = watershed(smooth, selected, [Peak(0., *seeds[0]), Peak(0., *seeds[1])])
    counts = [int((selected & (owners == owner)).sum()) for owner in (0, 1)]
    if min(counts) < max(6, min_height):
        return Assessment(
            "close", seeds=pair,
            saddle=_origin(lane, start, ridge), ratio=ratio,
            weakness=weaker.value / max(stronger.value, 1e-9), fraction=ridge.fraction,
            reason="拆出的其中一团太小，未达到最小带高，保留整带。")
    return Assessment(
        "split", seeds=pair,
        saddle=_origin(lane, start, ridge), ratio=ratio,
        weakness=weaker.value / max(stronger.value, 1e-9), fraction=ridge.fraction,
        reason=reason_for_split(ridge, ratio, weaker.value / max(stronger.value, 1e-9), pixels))
