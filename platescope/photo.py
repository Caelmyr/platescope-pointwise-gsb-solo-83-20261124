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
    front_line: tuple[tuple[float, float], tuple[float, float]] | None = None

    @property
    def tilted(self):
        return self.front_line is not None

    def front_y(self, x):
        """Solvent-front row at source column x (interpolated between endpoints)."""
        if self.front_line is None:
            return float(self.front)
        (x_left, y_left), (x_right, y_right) = self.front_line
        if x <= x_left:
            return float(y_left)
        if x >= x_right:
            return float(y_right)
        ratio = (x - x_left) / (x_right - x_left)
        return y_left + (y_right - y_left) * ratio

    def lane_box(self, number):
        x0, x1 = self.edges[number - 1], self.edges[number]
        if self.front_line is None:
            top = self.front
        else:
            top = int(np.floor(min(self.front_y(x) for x in range(x0, x1))))
        return x0, top, x1, self.origin + 1

    def lane_values(self, number):
        x0, y0, x1, y1 = self.lane_box(number)
        return self.values[y0:y1, x0:x1]

    def rf(self, y):
        return (self.origin - y) / (self.origin - self.front)

    def rf_grid(self, lane_number):
        """Rf of every (row, column) source pixel in a lane, NaN past its own front."""
        x0, y0, x1, _ = self.lane_box(lane_number)
        rows = np.arange(y0, self.origin + 1, dtype=np.float32)
        columns = np.arange(x0, x1, dtype=np.float32)
        if self.front_line is None:
            front_rows = np.full(columns.shape, self.front, dtype=np.float32)
        else:
            front_rows = np.array([self.front_y(x) for x in columns], dtype=np.float32)
        np.maximum(self.origin - front_rows, 1.0, out=front_rows)
        grid = (self.origin - rows[:, None]).astype(np.float32)
        grid = grid / front_rows[None, :]
        # 越过本列前沿的行不属于该列：置 NaN，汇总时按有限值筛选。
        grid[rows[:, None] < np.floor(self.origin - front_rows)[None, :]] = np.nan
        return grid


def observe(path, settings):
    with Image.open(path) as image:
        width, height = image.size
        x0, y0, x1, y1 = settings["roi"]
        left, right = round(x0 * width), round(x1 * width)
        top, bottom = round(y0 * height), round(y1 * height)
        front, origin = [round(settings[key] * (height - 1)) for key in ("front", "origin")]
        line = settings.get("front_line")
        front_line = None
        if line:
            front_line = tuple(
                (round(px * (width - 1)), round(py * (height - 1)))
                for px, py in line)
            front_here = min(y for _, y in front_line)
        else:
            front_here = front
        if right - left < 3 * settings["lanes"] or origin - front_here < 4:
            raise Invalid("板区的可读像素太少，请扩大范围或减少泳道。")
        edges = tuple(int(round(edge)) for edge in np.linspace(left, right, settings["lanes"] + 1))
        return View(pixel_values(image), (left, top, right, bottom), edges, front, origin, front_line)
