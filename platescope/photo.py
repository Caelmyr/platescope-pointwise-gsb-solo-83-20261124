"""Preserve oriented source data and map normalized controls to source pixels."""

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from image_lab.validation import Invalid

from .model import MAX_PIXELS, MAX_UPLOAD


def decode(blob):
    if not blob or len(blob) > MAX_UPLOAD:
        raise Invalid("选择 22 MB 以内的 PNG、TIFF 或 JPEG 照片。")
    try:
        with Image.open(BytesIO(blob)) as image:
            if image.format not in {"PNG", "TIFF", "JPEG"}:
                raise Invalid("选择 PNG、TIFF 或 JPEG 照片。")
            if min(image.size) < 32 or image.width * image.height > MAX_PIXELS:
                raise Invalid("照片每边至少 32 像素，总像素不能超过 1400 万。")
            oriented = ImageOps.exif_transpose(image)
            if oriented.mode in {"I", "I;16", "I;16B", "I;16L"}:
                values = np.asarray(oriented)
                if np.min(values) < 0 or np.max(values) > 65535:
                    raise Invalid("16 位灰度值应在 0 到 65535。")
                return Image.fromarray(values.astype(np.uint16))
            if oriented.mode == "L":
                return oriented.copy()
            if "A" in oriented.getbands() or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                return Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")
            return oriented.convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise Invalid("无法读取这张照片。") from None


def png(image):
    stream = BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def pixel_values(image):
    values = np.asarray(image).astype(np.float32)
    divisor = 255 if image.mode in {"RGB", "L"} else 65535
    return values / divisor


def display(path):
    with Image.open(path) as image:
        if image.mode in {"RGB", "L"}:
            return image.copy()
        return Image.fromarray(np.rint(pixel_values(image) * 255).astype(np.uint8))


@dataclass(frozen=True)
class View:
    values: np.ndarray
    region: tuple[int, int, int, int]
    edges: tuple[int, ...]
    front: int
    origin: int

    def lane_box(self, number):
        return self.edges[number - 1], self.front, self.edges[number], self.origin + 1

    def lane_values(self, number):
        x0, y0, x1, y1 = self.lane_box(number)
        return self.values[y0:y1, x0:x1]

    def rf(self, y):
        return (self.origin - y) / (self.origin - self.front)


def observe(path, settings):
    with Image.open(path) as image:
        width, height = image.size
        x0, y0, x1, y1 = settings["roi"]
        left, right = round(x0 * width), round(x1 * width)
        top, bottom = round(y0 * height), round(y1 * height)
        front, origin = [round(settings[key] * (height - 1)) for key in ("front", "origin")]
        if right - left < 3 * settings["lanes"] or origin - front < 4:
            raise Invalid("板区的可读像素太少，请扩大范围或减少泳道。")
        edges = tuple(int(round(edge)) for edge in np.linspace(left, right, settings["lanes"] + 1))
        return View(pixel_values(image), (left, top, right, bottom), edges, front, origin)
