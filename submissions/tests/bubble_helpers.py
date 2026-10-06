"""Procedural, synthetic layouts only; no student documents are committed."""

from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from submissions.recognition.bubbles import HEIGHT, TEMPLATES, WIDTH


def bubble_image(
    number="01234567",
    *,
    compact=False,
    fills=None,
    shade=0,
    missing_marker=False,
    written="99999999",
):
    template = TEMPLATES[int(compact)]
    image = Image.new("RGB", (1000, 1200), "white")
    draw = ImageDraw.Draw(image)
    ox, oy = 500, 150
    for index, (x, y) in enumerate(
        ((0, 0), (WIDTH - 1, 0), (WIDTH - 1, HEIGHT - 1), (0, HEIGHT - 1))
    ):
        if missing_marker and index == 3:
            continue
        draw.rectangle((ox + x - 6, oy + y - 6, ox + x + 6, oy + y + 6), fill="black")
    # Three separate QR-like finder patterns are decoys, never an identity.
    for x, y in ((90, 80), (140, 80), (90, 130)):
        draw.rectangle((x, y, x + 28, y + 28), fill="black")
        draw.rectangle((x + 4, y + 4, x + 24, y + 24), fill="white")
        draw.rectangle((x + 9, y + 9, x + 19, y + 19), fill="black")
    font = ImageFont.load_default(size=16)
    for column in range(template.columns):
        x = ox + round((template.first_x + column * template.pitch_x) * (WIDTH - 1))
        draw.text((x - 5, oy + 55), written[column], fill="black", font=font)
        for digit in range(template.rows):
            y = oy + round((template.first_y + digit * template.pitch_y) * (HEIGHT - 1))
            ry = 14 if compact else 13
            draw.ellipse(
                (x - 13, y - ry, x + 13, y + ry), outline=(100, 100, 100), width=2
            )
            draw.text((x - 5, y - 8), str(digit), fill=(130, 130, 130), font=font)
            marks = (
                fills.get(column, []) if fills is not None else [int(number[column])]
            )
            if digit in marks:
                draw.ellipse(
                    (x - 10, y - 10, x + 10, y + 10), fill=(shade, shade, shade)
                )
    return image


def png_bytes(image):
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def distorted_image(image, *, angle=0, perspective=False, shadow=False, scale=1):
    if angle:
        image = image.rotate(angle, expand=True, fillcolor="white")
    data = np.asarray(image).copy()
    height, width = data.shape[:2]
    if perspective:
        source = np.float32(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]
        )
        target = np.float32(
            [[55, 35], [width - 45, 0], [width - 1, height - 25], [0, height - 85]]
        )
        data = cv2.warpPerspective(
            data,
            cv2.getPerspectiveTransform(source, target),
            (width, height),
            borderValue=(255, 255, 255),
        )
    if shadow:
        data = (data * np.linspace(0.55, 1, width)[None, :, None]).astype(np.uint8)
    if scale != 1:
        data = cv2.resize(data, None, fx=scale, fy=scale)
    return Image.fromarray(data)
