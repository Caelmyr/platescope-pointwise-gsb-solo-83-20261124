"""A synthetic classroom pigment plate with reference and sample lanes."""

import numpy as np
from PIL import Image

from . import model, photo

WIDTH, HEIGHT = 760, 650
CENTERS = (152, 304, 456, 608)
FRONT, ORIGIN = 91, 559


def plate_photo():
    rng = np.random.default_rng(1107)
    y, x = np.ogrid[:HEIGHT, :WIDTH]
    paper = 0.96 - .025 * (x / WIDTH) - .017 * (y / HEIGHT)
    texture = rng.normal(0, .0035, size=(HEIGHT, WIDTH))
    canvas = (paper + texture)[:, :, None] * np.array([1, .985, .946])
    canvas[52:55] *= .75
    canvas[595:599] *= .75
    canvas[FRONT - 1:FRONT + 1, 80:680] *= .94
    canvas[ORIGIN, 80:680] *= .90
    pigments = ((.62, .32, .10), (.40, .69, .11), (.15, .39, .70))
    spots = (
        [(0.20, 0, 1.0, 8), (0.43, 1, .96, 9), (0.68, 2, .94, 9)],
        [(0.23, 0, .78, 10), (0.47, 1, .80, 9), (0.72, 2, 1.0, 11)],
        [(0.21, 0, .92, 10), (0.44, 1, .62, 9), (0.61, 2, .82, 8), (.76, 2, .65, 8)],
        [(0.31, 0, .74, 11), (0.52, 1, 1.0, 15), (0.71, 2, .64, 11)],
    )
    for x_center, lane in zip(CENTERS, spots):
        for rf, color, strength, height in lane:
            center = ORIGIN - rf * (ORIGIN - FRONT)
            distance = y - center
            spread = np.where(distance > 0, height * (1.55 if color == 1 else 1.1), height)
            shape = np.exp(-((x - x_center) / 24) ** 2 / 2 - (distance / spread) ** 2 / 2)
            canvas -= shape[:, :, None] * np.array(pigments[color]) * strength
    return Image.fromarray(np.clip(canvas * 255, 0, 255).astype(np.uint8))


def create(library):
    image = plate_photo()
    return library.create("练习板 · 墨水色带", "ink-plate-synthetic.png", photo.png(image),
                          image.size, model.DEFAULTS, {"kind": "synthetic"})
