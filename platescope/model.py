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
    "splits": [],
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


def splits(value):
    if not isinstance(value, list):
        raise Invalid("显色带拆分应为列表。")
    if len(value) > 120:
        raise Invalid("保存的显色带拆分过多。")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise Invalid("显色带拆分格式不正确。")
        lane = numeric(item.get("lane"), "拆分泳道", 1, 12, True)
        seeds = item.get("seeds")
        if not isinstance(seeds, list) or len(seeds) != 2:
            raise Invalid("显色带拆分缺两条种子位置。")
        pairs = []
        for seed in seeds:
            if not isinstance(seed, list) or len(seed) != 2:
                raise Invalid("显色带拆分种子格式不正确。")
            pairs.append([numeric(item_, "拆分种子", 0, 1_000_000, True) for item_ in seed])
        if pairs[0] == pairs[1]:
            raise Invalid("显色带拆分的两条种子不能重合。")
        result.append({"lane": lane, "seeds": sorted(pairs)})
    return result


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
        "splits": splits(chosen.get("splits", [])),
    }


def mode(value):
    if not isinstance(value, str) or value not in MODES:
        raise Invalid("请选择一种读板方式。")
    return value
