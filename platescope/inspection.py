"""Plate results for the original-image canvas, archive and downloads."""

from dataclasses import dataclass, field

import numpy as np

from .model import MODES
from . import reference, signals

CURRENT = "#198777"
STANDARDS = "#9e532d"
GUIDE = "#398387"
PARTS = ("#166958", "#ac5619")


@dataclass
class Report:
    mode: str
    settings: dict
    metrics: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    marks: list = field(default_factory=list)
    plot: dict | None = None
    suggestions: list = field(default_factory=list)

    def metric(self, label, value, units=""):
        self.metrics.append({"label": label, "value": value, "units": units})

    def row(self, label, value, detail="", at=None):
        self.rows.append({"label": label, "value": value, "detail": detail, "at": at})

    def mark(self, kind, coords, color, label=""):
        x0, y0, x1, y1 = coords
        self.marks.append({"type": kind, "points": [[x0, y0], [x1, y1]], "color": color, "label": label})

    def band(self, band, color=CURRENT, prefix=""):
        label = f"{prefix}{band.parent}" + (f"·{band.part}" if band.part else "")
        tint = PARTS[(band.part or 1) - 1] if band.part else color
        self.mark("box", band.box, tint, label)

    def document(self):
        return {**vars(self), "heading": MODES[self.mode]}


def lane_bands(view, report, number):
    scan = signals.scan(view, number, report.settings["channel"])
    return signals.bands(view, scan, report.settings)


def band_label(band):
    return f"带 {band.parent} 第 {band.part}/2 团" if band.part else f"带 {band.number}"


def split_note(band):
    if band.part:
        return (f"拆分第 {band.part}/2 团 · 计入支持区 {band.pixels} px · "
                f"显色积分 {band.amount:.1f}")
    return f"Rf · 支持区 {band.pixels} px · 显色积分 {band.amount:.1f}"


def split_suggestions(bands):
    found = []
    for band in bands:
        if band.suggestion and band.suggestion.get("verdict") == "split":
            found.append({"band": band.number, **band.suggestion})
    return found


def lost_split(out, bands):
    """A saved split was requested for this lane but no part was produced."""
    lane = out.settings["lane"]
    requested = [entry for entry in out.settings.get("splits", []) if entry.get("lane") == lane]
    applied = any(band.part for band in bands)
    if requested and not applied:
        out.row("已保存的拆分", "本次未套用",
                "标定或阈值改动后，两条种子不再落在同一条显色带内，整带保留。")


def retained_notes(bands):
    notes = []
    for band in bands:
        note = band.suggestion
        if not note or note.get("verdict") == "split":
            continue
        if note.get("verdict") == "single":
            continue
        notes.append((band, note["reason"]))
    return notes


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
    out.metric("原带", len({band.parent for band in bands}), "条")
    out.metric("迁移距离", view.origin - view.front, "px")
    out.metric("显色积分", round(sum(band.amount for band in bands), 1))
    for band in bands:
        out.band(band, prefix="带")
        out.row(band_label(band), round(band.rf, 4), split_note(band), band.center)
    out.suggestions.extend(split_suggestions(bands))
    for band, reason in retained_notes(bands):
        out.row(band_label(band), "保留整带", reason, band.center)
    lost_split(out, bands)


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
    if any(band.part for band in bands):
        series = signals.series(view, lane, bands)
        out.plot = {"label": "Rf 与逐团显色（每团计入像素的显色和）",
                    "samples": series[0]["samples"] if series else [], "series": series}
    else:
        indexes = np.unique(np.linspace(len(lane.profile) - 1, 0, min(len(lane.profile), 550)).round().astype(int))
        x = (x0 + x1 - 1) // 2
        out.plot = {"label": "Rf 与道内平均显色", "samples": [
            {"x": round(view.rf(y0 + int(i)), 6), "y": round(float(lane.profile[i]), 6), "at": [x, y0 + int(i)]}
            for i in reversed(indexes)]}
    out.metric("平均显色峰值", round(float(lane.profile.max()), 4))
    out.metric("显色带", len(bands), "条")
    out.metric("原带", len({band.parent for band in bands}), "条")
    for band in bands:
        out.band(band, prefix="带")
        detail = (f"拆分第 {band.part}/2 团 · 计入 {band.pixels} px · 峰值 {band.peak:.4f}"
                  if band.part else f"峰值 · Rf {band.rf:.4f}")
        out.row(band_label(band), round(band.rf, 4), detail, band.center)
    out.suggestions.extend(split_suggestions(bands))
    for band, reason in retained_notes(bands):
        out.row(band_label(band), "保留整带", reason, band.center)
    lost_split(out, bands)


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
    pairs = reference.lookup(samples, standard, out.settings["tolerance"])
    out.metric("容差内", sum(pair.reference is not None for pair in pairs), "条")
    for band in standard:
        out.band(band, STANDARDS, "参")
    for band, pair in zip(samples, pairs):
        out.band(band, CURRENT, "样")
        result = f"参照带 {pair.reference}" if pair.reference is not None else "未找到"
        delta = f"最近 |ΔRf| {pair.distance:.4f}" if pair.distance is not None else "参照道无可读带"
        out.row(band_label(band), result, f"Rf {band.rf:.4f} · {delta}", band.center)


def amount_report(view, out):
    samples, standard = pair_lanes(view, out)
    sample, ref, value = reference.relative_amount(samples, standard,
                                                  out.settings["sample_band"], out.settings["reference_band"])
    out.metric("相对显色量", round(value, 2) if value is not None else "无读数", "%" if value is not None else "")
    out.metric("当前道可用带", len(samples), "条")
    out.metric("参照道可用带", len(standard), "条")
    for label, band, ink in (("样品带", sample, CURRENT), ("参照带", ref, STANDARDS)):
        if band is not None:
            out.band(band, ink, label)
            out.row(band_label(band), round(band.amount, 2),
                    f"显色积分 · Rf {band.rf:.4f}", band.center)
        else:
            out.row(label, "没有该序号", "可先查看显色带或参照查找。")


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
        out.row(band_label(band), round(band.tail, 3) if band.tail is not None else "超出带界",
                f"向起跑线一侧 / 向前沿一侧半高宽 · Rf {band.rf:.4f}", band.center)


def colors_report(view, out):
    bands = lane_bands(view, out, out.settings["lane"])
    out.metric("显色带", len(bands), "条")
    out.metric("原带", len({band.parent for band in bands}), "条")
    for band in bands:
        out.band(band, prefix="带")
        components = band.components
        labels = ("R", "G", "B") if len(components) == 3 else ("灰度",)
        total = sum(components)
        text = " · ".join(f"{label} {part / total * 100:.1f}%" for label, part in zip(labels, components))
        out.row(band_label(band), round(band.rf, 4), text, band.center)


REPORTERS = dict(spots=spot_report, lanes=lanes_report, profile=profile_report,
                 matches=matches_report, amount=amount_report, background=background_report,
                 tails=tails_report, colors=colors_report)


def report(view, mode, settings):
    out = Report(mode, settings)
    coordinates(view, out)
    REPORTERS[mode](view, out)
    return out.document()
