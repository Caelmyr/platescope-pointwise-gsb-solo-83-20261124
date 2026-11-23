"""Plate results for the original-image canvas, archive and downloads."""

from dataclasses import dataclass, field

import numpy as np

from .model import MODES
from . import reference, signals

CURRENT = "#198777"
STANDARDS = "#9e532d"
GUIDE = "#398387"


@dataclass
class Report:
    mode: str
    settings: dict
    metrics: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    marks: list = field(default_factory=list)
    plot: dict | None = None
    association: dict | None = None

    def metric(self, label, value, units=""):
        self.metrics.append({"label": label, "value": value, "units": units})

    def row(self, label, value, detail="", at=None):
        self.rows.append({"label": label, "value": value, "detail": detail, "at": at})

    def mark(self, kind, coords, color, label=""):
        x0, y0, x1, y1 = coords
        self.marks.append({"type": kind, "points": [[x0, y0], [x1, y1]], "color": color, "label": label})

    def band(self, band, color=CURRENT, prefix=""):
        self.mark("box", band.box, color, f"{prefix}{band.number}")

    def document(self):
        return {**vars(self), "heading": MODES[self.mode]}


def lane_bands(view, report, number):
    scan = signals.scan(view, number, report.settings["channel"])
    return signals.bands(view, scan, report.settings)


def effective_settings(view, mode, settings):
    """Drop a stale adopted association before a report is computed.

    The association belongs to a specific lane/tolerance/band-detection setup.
    If any affecting setting changed, or its pairs no longer appear among the
    adoptable suggestions for the bands currently detected, it is recomputed
    by the matches report instead of being reused.
    """
    adopted = settings.get("association") or {}
    basis = settings.get("association_basis")
    if not settings.get("association_active"):
        return {**settings, "association": {}, "association_active": False}
    current_basis = reference.adoption_key(settings)
    if basis != current_basis:
        return {**settings, "association": {}, "association_basis": None,
                "association_active": False}
    if mode in {"matches", "amount"}:
        sample_scan = signals.scan(view, settings["lane"], settings["channel"])
        reference_scan = signals.scan(view, settings["reference"], settings["channel"])
        samples = signals.bands(view, sample_scan, settings)
        standard = signals.bands(view, reference_scan, settings)
        _, suggestions = reference.lookup(samples, standard, settings["tolerance"])
        allowed_pairs = {frozenset((pair["sample"], pair["reference"]))
                         for suggestion in suggestions for pair in suggestion.pairs}
        if any(frozenset(item) not in allowed_pairs for item in adopted.items()):
            return {**settings, "association": {}, "association_basis": None,
                    "association_active": False}
    return settings


def coordinates(view, out):
    x0, y0, x1, y1 = view.region
    out.mark("box", (x0, y0, x1 - 1, y1 - 1), GUIDE)
    out.mark("line", (x0, view.front, x1 - 1, view.front), GUIDE, "溶剂前沿")
    out.mark("line", (x0, view.origin, x1 - 1, view.origin), GUIDE, "起跑线")
    for x in view.edges[1:-1]:
        out.mark("line", (x, view.front, x, view.origin), GUIDE)


def spot_report(view, out):
    bands = lane_bands(view, out, out.settings["lane"])
    out.metric("显色带", len(bands), "条")
    out.metric("迁移距离", view.origin - view.front, "px")
    out.metric("显色积分", round(sum(band.amount for band in bands), 1))
    for band in bands:
        out.band(band, prefix="带")
        out.row(f"带 {band.number}", round(band.rf, 4),
                f"Rf · 支持区 {band.pixels} px · 显色积分 {band.amount:.1f}", band.center)


def lanes_report(view, out):
    counts = []
    for number in range(1, out.settings["lanes"] + 1):
        found = lane_bands(view, out, number)
        counts.append(len(found))
        left, top, right, bottom = view.lane_box(number)
        out.row(f"泳道 {number}", f"{len(found)} 条", f"道宽 {right - left} px",
                ((left + right - 1) // 2, (top + bottom - 1) // 2))
        for band in found:
            out.band(band, prefix=f"{number}.")
    out.metric("泳道数", len(counts))
    out.metric("有带泳道", sum(count > 0 for count in counts))
    out.metric("全板显色带", sum(counts), "条")


def profile_report(view, out):
    lane = signals.scan(view, out.settings["lane"], out.settings["channel"])
    bands = signals.bands(view, lane, out.settings)
    x0, y0, x1, _ = lane.box
    indexes = np.unique(np.linspace(len(lane.profile) - 1, 0, min(len(lane.profile), 550)).round().astype(int))
    x = (x0 + x1 - 1) // 2
    out.plot = {"label": "Rf 与道内平均显色", "samples": [
        {"x": round(view.rf(y0 + int(i)), 6), "y": round(float(lane.profile[i]), 6), "at": [x, y0 + int(i)]}
        for i in reversed(indexes)]}
    out.metric("平均显色峰值", round(float(lane.profile.max()), 4))
    out.metric("显色带", len(bands), "条")
    for band in bands:
        out.band(band, prefix="带")
        out.row(f"带 {band.number}", round(band.peak, 4), f"峰值 · Rf {band.rf:.4f}", band.center)


def pair_lanes(view, out):
    sample = out.settings["lane"]
    standard = out.settings["reference"]
    return lane_bands(view, out, sample), lane_bands(view, out, standard)


def matches_report(view, out):
    samples, standard = pair_lanes(view, out)
    repeated = out.settings["lane"] == out.settings["reference"]
    out.metric("样品带", len(samples), "条")
    out.metric("参照带", len(standard), "条")
    if repeated:
        out.row("请选择另一条参照道", "同道不可比")
        return
    pairs, suggestions = reference.lookup(samples, standard, out.settings["tolerance"])
    adopted = out.settings.get("association") or {}
    active = bool(out.settings.get("association_active"))
    out.metric("容差内", sum(pair.reference is not None for pair in pairs), "条")
    basis = reference.adoption_key(out.settings)
    out.association = {
        "suggestions": [vars(suggestion) for suggestion in suggestions],
        "adopted": adopted if active else {},
        "basis": basis,
    }
    if len(suggestions) > 1:
        cautious, balanced = suggestions if suggestions[0].strategy == "cautious" else (suggestions[1], suggestions[0])
        out.row("取舍建议 · 先稳单条", f"最偏 |ΔRf| {cautious.max_distance:.4f}",
                f"整组合计 {cautious.total_distance:.4f} · {cautious.rationale}")
        out.row("取舍建议 · 先压总量", f"合计 |ΔRf| {balanced.total_distance:.4f}",
                f"最偏一条 {balanced.max_distance:.4f} · {balanced.rationale}")
        out.row("建议默认", "先稳单条", "两组认定条数相同；怕某一条勉强配错时选它，要整组最紧时换用另一组。")
    for band in standard:
        out.band(band, STANDARDS, "参")
    shown = adopted if active else {pair.sample: pair.reference for pair in pairs
                                    if pair.reference is not None}
    for band, pair in zip(samples, pairs):
        out.band(band, CURRENT, "样")
        reference_number = shown.get(band.number)
        result = f"参照带 {reference_number}" if reference_number is not None else "未找到"
        delta = f"最近 |ΔRf| {pair.distance:.4f}" if pair.distance is not None else "参照道无可读带"
        out.row(f"样品带 {band.number}", result, f"Rf {band.rf:.4f} · {delta}", band.center)


def amount_report(view, out):
    samples, standard = pair_lanes(view, out)
    adopted = out.settings.get("association") or {}
    adoption_active = bool(out.settings.get("association_active"))
    chosen_sample = out.settings["sample_band"]
    if adoption_active:
        # No manual fallback: an unmatched sample band stays without a reference.
        chosen_reference = adopted.get(chosen_sample)
    else:
        chosen_reference = out.settings["reference_band"]
    sample, ref, value = reference.relative_amount(samples, standard, chosen_sample, chosen_reference)
    auto_reference = adoption_active and chosen_sample in adopted
    if adoption_active and chosen_sample not in adopted and sample is not None:
        display_value, units = "无参照", ""
    else:
        display_value = round(value, 2) if value is not None else "无读数"
        units = "%" if value is not None else ""
    out.metric("相对显色量", display_value, units)
    out.metric("当前道可用带", len(samples), "条")
    out.metric("参照道可用带", len(standard), "条")
    if adoption_active:
        out.association = {"adopted": adopted, "active": chosen_sample,
                          "basis": reference.adoption_key(out.settings)}
    for label, band, ink in (("样品带", sample, CURRENT), ("参照带", ref, STANDARDS)):
        if band is not None:
            out.band(band, ink, label)
            out.row(f"{label} {band.number}", round(band.amount, 2), f"显色积分 · Rf {band.rf:.4f}", band.center)
        elif label == "参照带" and adoption_active:
            out.row("参照带", "无参照", "该样品带在参照查找中未认到，保留样品带读数。")
        else:
            out.row(label, "没有该序号", "可先查看显色带或参照查找。")
    if auto_reference and ref is not None:
        out.row("认定来源", f"参照带 {ref.number}", "来自本次采用的参照查找认定；换道或改设置后会重新认定。")
    elif adoption_active and chosen_sample not in adopted:
        out.row("认定来源", "无参照", "该样品带不在本次采用的认定中；换道或改设置后会重新认定。")


def background_report(view, out):
    scan = signals.scan(view, out.settings["lane"], out.settings["channel"])
    base = scan.original.mean(axis=2)
    out.metric("亮部饱和", round(float((scan.original.max(axis=2) >= .995).mean()) * 100, 2), "%")
    out.metric("极暗像素", round(float((base <= .02).mean()) * 100, 2), "%")
    x0, y0, x1, _ = scan.box
    values = []
    for index, part in enumerate(np.array_split(base, min(8, len(base)), axis=0), 1):
        bright = float(np.quantile(part, .85))
        to = y0 + len(part)
        values.append(bright)
        out.row(f"区段 {index}", round(bright, 4), "原片亮度 P85",
                ((x0 + x1 - 1) // 2, (y0 + to - 1) // 2))
        out.mark("box", (x0, y0, x1 - 1, to - 1), CURRENT)
        y0 = to
    out.metric("亮底极差", round(max(values) - min(values), 4))


def tails_report(view, out):
    bands = lane_bands(view, out, out.settings["lane"])
    out.metric("可读拖尾", sum(band.tail is not None for band in bands), "条")
    for band in bands:
        out.band(band, prefix="带")
        out.row(f"带 {band.number}", round(band.tail, 3) if band.tail is not None else "超出带界",
                f"向起跑线一侧 / 向前沿一侧半高宽 · Rf {band.rf:.4f}", band.center)


def colors_report(view, out):
    bands = lane_bands(view, out, out.settings["lane"])
    out.metric("显色带", len(bands), "条")
    for band in bands:
        out.band(band, prefix="带")
        components = band.components
        labels = ("R", "G", "B") if len(components) == 3 else ("灰度",)
        total = sum(components)
        text = " · ".join(f"{label} {part / total * 100:.1f}%" for label, part in zip(labels, components))
        out.row(f"带 {band.number}", round(band.rf, 4), text, band.center)


REPORTERS = dict(spots=spot_report, lanes=lanes_report, profile=profile_report,
                 matches=matches_report, amount=amount_report, background=background_report,
                 tails=tails_report, colors=colors_report)


def report(view, mode, settings):
    settings = effective_settings(view, mode, settings)
    out = Report(mode, settings)
    coordinates(view, out)
    REPORTERS[mode](view, out)
    document = out.document()
    if mode in {"matches", "amount"}:
        document["association_basis"] = reference.adoption_key(settings)
    return document
