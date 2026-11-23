"""Photo, lane, migration and display settings accepted by the plate desk."""

from math import isfinite

from image_lab.validation import Invalid

MAX_UPLOAD = 22 * 1024**2
MAX_PIXELS = 14_000_000
MODES = {
    "spots": "显色带",
    "lanes": "泳道质检",
    "profile": "显色曲线",
    "matches": "参照查找",
    "amount": "相对显色量",
    "background": "底色巡检",
    "tails": "拖尾读数",
    "colors": "色彩分量",
}
DEFAULTS = {
    "roi": [.1, .08, .9, .92],
    "front": .14,
    "front_line": None,
    "origin": .86,
    "lanes": 4,
    "lane": 2,
    "reference": 1,
    "sample_band": 1,
    "reference_band": 1,
    "channel": "auto",
    "cutoff": .095,
    "min_height": 5,
    "tolerance": .10,
}
# Rf 分箱在最短跑程一列至少覆盖多少个原片行。短侧每箱都有真实像素，
# 同时全道共用同一 Rf 网格，避免按列各自重采样产生的虚假尖峰。
BIN_PIXEL_FLOOR = 2.0
# Rf 空间平滑量（以分箱宽度计）。约等于旧读法 1.3 px 的行平滑，
# 在短跑程一侧平滑随分箱自动变宽，不额外吃掉细带。
BIN_SMOOTH = 1.0
# 两端高度差小于该比例时视为水平前沿，直接走原来的整行平均读法。
LEVEL_TOLERANCE = 1e-3
CHANNELS = {"auto": "最强显色", "red": "红光", "green": "绿光", "blue": "蓝光"}


def object_value(value):
    if not isinstance(value, dict):
        raise Invalid("读板设置应为对象。")
    return value


def text_value(value, field="照片名称"):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 100:
        raise Invalid(f"{field}应有 1 至 100 个字符。")
    return " ".join(value.split())


def numeric(value, label, start, stop, integer=False):
    if isinstance(value, bool):
        raise Invalid(f"{label}超出可用范围。")
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise Invalid(f"{label}需要填写数字。") from None
    if not isfinite(number) or not start <= number <= stop or (integer and not number.is_integer()):
        raise Invalid(f"{label}超出可用范围。")
    return int(number) if integer else number


def front_line_value(value, rect, origin):
    """Two normalized solvent-front endpoints; None keeps the single horizontal line."""
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise Invalid("溶剂前沿应点出左、右两个端点。")
    points = []
    for point in value:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise Invalid("溶剂前沿端点应为板上的坐标点。")
        px = numeric(point[0], "前沿端点横向", rect[0], rect[2])
        py = numeric(point[1], "前沿端点纵向", rect[1], rect[3])
        points.append([px, py])
    left, right = sorted(points, key=lambda point: point[0])
    if right[0] - left[0] < .02:
        raise Invalid("前沿两个端点应分别靠近板区的左、右两侧。")
    if max(left[1], right[1]) >= origin - .04:
        raise Invalid("溶剂前沿应在起跑线上方，两线之间须有可读距离。")
    if abs(left[1] - right[1]) <= LEVEL_TOLERANCE:
        # 两端水平：折叠成旧的单横线，照旧读法处理。
        return None
    return left, right


def settings(value, fallback):
    chosen = {**fallback, **object_value(value)}
    rect = chosen["roi"]
    if not isinstance(rect, list) or len(rect) != 4:
        raise Invalid("请重新框选色谱板。")
    x0, y0, x1, y1 = [numeric(item, "板区", 0, 1) for item in rect]
    if x1 - x0 < .06 or y1 - y0 < .08:
        raise Invalid("板区太小，请重新框选。")
    front = numeric(chosen["front"], "溶剂前沿", y0, y1)
    origin = numeric(chosen["origin"], "起跑线", y0, y1)
    if origin - front < .04:
        raise Invalid("溶剂前沿应在起跑线上方，两线之间须有可读距离。")
    front_line = front_line_value(chosen.get("front_line"), [x0, y0, x1, y1], origin)
    lanes = numeric(chosen["lanes"], "泳道数", 1, 12, True)
    channel = chosen["channel"]
    if not isinstance(channel, str) or channel not in CHANNELS:
        raise Invalid("请选择一种显色通道。")
    return {
        "roi": [x0, y0, x1, y1], "front": front, "front_line": front_line,
        "origin": origin,
        "lanes": lanes, "lane": numeric(chosen["lane"], "当前道", 1, lanes, True),
        "reference": numeric(chosen["reference"], "参照道", 1, lanes, True),
        "sample_band": numeric(chosen["sample_band"], "样品带序号", 1, 128, True),
        "reference_band": numeric(chosen["reference_band"], "参照带序号", 1, 128, True),
        "channel": channel, "cutoff": numeric(chosen["cutoff"], "显色阈值", .01, .95),
        "min_height": numeric(chosen["min_height"], "最小带高", 1, 200, True),
        "tolerance": numeric(chosen["tolerance"], "Rf 容差", 0, .5),
    }


def mode(value):
    if not isinstance(value, str) or value not in MODES:
        raise Invalid("请选择一种读板方式。")
    return value
