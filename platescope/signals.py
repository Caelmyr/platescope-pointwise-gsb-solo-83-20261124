"""Local paper response and vertically connected pigment bands.

水平前沿沿用原来的整行平均读法；倾斜前沿先把每列像素按该列自己的
跑程折算成 Rf，再把整条泳道汇入同一个 Rf 网格，得到一条显色曲线。
"""

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d

from .model import BIN_PIXEL_FLOOR, BIN_SMOOTH

COLORS = ("red", "green", "blue")


@dataclass(frozen=True)
class LaneSignal:
    box: tuple
    original: np.ndarray
    background: np.ndarray
    components: np.ndarray
    density: np.ndarray
    profile: np.ndarray
    # 倾斜前沿读法专用；水平读法保持上面的像素行索引字段。
    rf_edges: np.ndarray | None = None
    rf_profile: np.ndarray | None = None
    rf_support: np.ndarray | None = None
    rf_grid: np.ndarray | None = None
    rf_weight: np.ndarray | None = None


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


def channel_density(components, channel):
    if channel == "auto":
        return components.max(axis=2)
    return components[:, :, min(components.shape[2] - 1, COLORS.index(channel))]


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
    density = channel_density(components, channel)
    # Give lane edges less weight against plate-border marks and nearby lanes.
    inset = min((width - 1) // 2, width // 9)
    if view.tilted:
        return tilted_scan(view, numbering, box, original, background, components, density, inset)
    core = density[:, inset:width - inset]
    profile = gaussian_filter1d(core.mean(axis=1), sigma=1.3, mode="nearest")
    return LaneSignal(box, original, background, components, density, profile)


def tilted_scan(view, numbering, box, original, background, components, density, inset):
    """Pool every column onto its own run length, then into one Rf grid."""
    x0, _, x1, _ = box
    width = density.shape[1]
    grid = view.rf_grid(numbering)
    core_density = density[:, inset:width - inset]
    core_grid = grid[:, inset:width - inset]
    valid = np.isfinite(core_grid)
    # 分箱宽度由最短跑程决定：最短的一列在每个箱内至少有 BIN_PIXEL_FLOOR
    # 个真实像素行，短跑程一侧不会出现没有像素支持的空箱和插值尖峰。
    min_run = float(min((view.origin - view.front_y(x)) for x in range(x0 + inset, x1 - inset)))
    bin_count = max(4, min(550, int(min_run // BIN_PIXEL_FLOOR)))
    edges = np.linspace(0.0, 1.0 + 1e-9, bin_count + 1)
    index = np.clip(np.searchsorted(edges, core_grid[valid], side="right") - 1, 0, bin_count - 1)
    sums = np.bincount(index, weights=core_density[valid], minlength=bin_count)
    support = np.bincount(index, minlength=bin_count).astype(np.float64)
    profile = np.where(support > 0, sums / np.maximum(support, 1.0), 0.0)
    # 平滑量按 Rf 分箱宽度计；短侧分箱更宽，平滑随之变宽，细带一侧仍只占一两箱。
    profile = gaussian_filter1d(profile, sigma=BIN_SMOOTH, mode="nearest").astype(np.float32)
    # 越界列像素不参与任何带的加权：直接在本道显色图上清零，避免再存一份同尺寸权重。
    density = np.where(np.isfinite(grid), density, 0.0).astype(np.float32)
    return LaneSignal(box, original, background, components, density, profile,
                      edges, profile, support, grid, density)


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
    if view.tilted:
        return tilted_bands(view, lane, settings)
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


def tilted_bands(view, lane, settings):
    """Band detection on the shared Rf profile; boxes and Rf use each column's run."""
    x0, y0, x1, _ = lane.box
    edges = lane.rf_edges
    # 最小带高从像素折算成 Rf 箱数，按道内中位跑程换算，水平/倾斜读法尺度一致。
    runs = np.array([view.origin - view.front_y(x) for x in range(x0, x1)])
    median_run = float(np.median(runs))
    bin_width_rf = 1.0 / (len(edges) - 1)
    min_bins = max(1, int(round(settings["min_height"] / (median_run * bin_width_rf))))
    regions = intervals(lane.rf_profile >= settings["cutoff"], min_bins)
    result = []
    grid, weight = lane.rf_grid, lane.rf_weight
    height = grid.shape[0]
    for number, (start, stop) in enumerate(reversed(regions), 1):
        rf_lo, rf_hi = edges[start], edges[stop]
        upper = np.floor(view.origin - rf_hi * np.maximum(runs, 1.0)).astype(int) - y0
        lower = np.ceil(view.origin - rf_lo * np.maximum(runs, 1.0)).astype(int) - y0
        upper = np.clip(upper, 0, height - 1)
        lower = np.clip(lower, 0, height - 1)
        row_lo, row_hi = int(upper.min()), int(lower.max()) + 1
        sub_grid = grid[row_lo:row_hi]
        sub_weight = weight[row_lo:row_hi]
        selected = (sub_grid >= rf_lo) & (sub_grid < rf_hi) & (sub_weight >= settings["cutoff"] * .4)
        rows, columns = np.nonzero(selected)
        if not rows.size:
            continue
        rows += row_lo
        weights = sub_weight[selected]
        amount = float(weights.sum(dtype=np.float64))
        lx = x0 + int(round(np.average(columns, weights=weights)))
        ly = y0 + int(round(np.average(rows, weights=weights)))
        rf = float(np.average(grid[rows, columns], weights=weights))
        box = (x0 + int(columns.min()), y0 + int(rows.min()),
               x0 + int(columns.max()), y0 + int(rows.max()))
        traces = tuple(float(value) for value in lane.components[rows, columns].sum(axis=0, dtype=np.float64))
        result.append(Band(number, box, (lx, ly), rf, float(lane.rf_profile[start:stop].max()),
                           int(rows.size), amount, traces,
                           tail_factor(lane.rf_profile, start, stop)))
    return result
