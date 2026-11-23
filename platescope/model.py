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
    "association": {},
    "association_basis": None,
    "association_active": False,
}
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


def clean_association(value):
    """Validate an adopted sample-to-reference band map; discard invalid input.

    JSON storage turns integer keys into strings, so numeric strings are
    coerced back while booleans and other non-numeric values are rejected.
    """
    if not isinstance(value, dict):
        return {}
    result = {}
    for sample, standard in value.items():
        if isinstance(sample, bool) or isinstance(standard, bool):
            return {}
        sample = int(sample) if isinstance(sample, str) and sample.isdigit() else sample
        standard = int(standard) if isinstance(standard, str) and standard.isdigit() else standard
        if not isinstance(sample, int) or not isinstance(standard, int):
            return {}
        if not 1 <= sample <= 128 or not 1 <= standard <= 128:
            return {}
        if sample in result or standard in result.values():
            return {}
        result[sample] = standard
    return result


def clean_basis(value):
    """Accept only a basis object whose keys are the association-affecting fields."""
    if not isinstance(value, dict):
        return None
    fields = ("lane", "reference", "tolerance", "roi", "front", "origin", "lanes",
              "channel", "cutoff", "min_height")
    if set(value) != set(fields):
        return None
    return value


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
    lanes = numeric(chosen["lanes"], "泳道数", 1, 12, True)
    channel = chosen["channel"]
    if not isinstance(channel, str) or channel not in CHANNELS:
        raise Invalid("请选择一种显色通道。")
    return {
        "roi": [x0, y0, x1, y1], "front": front, "origin": origin,
        "lanes": lanes, "lane": numeric(chosen["lane"], "当前道", 1, lanes, True),
        "reference": numeric(chosen["reference"], "参照道", 1, lanes, True),
        "sample_band": numeric(chosen["sample_band"], "样品带序号", 1, 128, True),
        "reference_band": numeric(chosen["reference_band"], "参照带序号", 1, 128, True),
        "channel": channel, "cutoff": numeric(chosen["cutoff"], "显色阈值", .01, .95),
        "min_height": numeric(chosen["min_height"], "最小带高", 1, 200, True),
        "tolerance": numeric(chosen["tolerance"], "Rf 容差", 0, .5),
        "association": clean_association(chosen.get("association")),
        "association_basis": clean_basis(chosen.get("association_basis")),
        "association_active": chosen.get("association_active") is True,
    }


def mode(value):
    if not isinstance(value, str) or value not in MODES:
        raise Invalid("请选择一种读板方式。")
    return value
