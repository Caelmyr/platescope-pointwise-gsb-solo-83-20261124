"""Plate output uses the exact saved marks and recorded coordinates."""

import csv
from io import StringIO

from PIL import ImageDraw


def csv_text(result):
    stream = StringIO()
    writer = csv.writer(stream)
    writer.writerow(["field", "value", "details", "original_x", "original_y"])
    writer.writerow(["mode", result["heading"], result.get("title", "")])
    writer.writerow(["migration", result["settings"]["front"], result["settings"]["origin"]])
    for metric in result["metrics"]:
        writer.writerow([metric["label"], metric["value"], metric["units"]])
    for row in result["rows"]:
        at = row.get("at") or ["", ""]
        writer.writerow([row["label"], row["value"], row["detail"], *at])
    if result.get("plot"):
        writer.writerow(["plot_x", "plot_y", result["plot"]["label"]])
        writer.writerows((point["x"], point["y"]) for point in result["plot"]["samples"])
    return stream.getvalue()


def overlay(image, result):
    composed = image.convert("RGB")
    draw = ImageDraw.Draw(composed)
    width = max(1, round(image.width / 650))
    for mark in result["marks"]:
        points = [tuple(point) for point in mark["points"]]
        color = mark["color"]
        if mark["type"] == "box":
            draw.rectangle(points, outline=color, width=width)
        elif mark["type"] == "polygon":
            draw.line(points + [points[0]], fill=color, width=width)
        else:
            draw.line(points, fill=color, width=width + 1)
    return composed
