"""Registration-marker optical mark recognition. This module never uses OCR."""
from dataclasses import dataclass
from itertools import combinations

import cv2
import numpy as np


@dataclass(frozen=True)
class BubbleTemplate:
    version: str
    columns: int = 8
    rows: int = 10
    first_x: float = 0.103
    pitch_x: float = 0.1134
    first_y: float = 0.237
    pitch_y: float = 0.077
    radius_y_scale: float = 1.0


TEMPLATES = (
    BubbleTemplate("nwu-eight-standard-1"),
    BubbleTemplate("nwu-eight-compact-1", first_x=0.109, pitch_x=0.1115, first_y=0.17, pitch_y=0.0835, radius_y_scale=1.1),
)
PROCESSING_VERSION = "bubble-1"
WIDTH, HEIGHT = 320, 520
# These are mark-density and separation thresholds, not probabilities.
CLEAR_FILL = 0.23
POSSIBLE_FILL = 0.10
MIN_MARGIN = 0.12


@dataclass
class BubbleReading:
    candidate: str = ""
    columns: list | None = None
    ambiguity: list | None = None
    region: dict | None = None
    template: str = ""
    image: bytes | None = None
    confidence: float | None = None
    reason: str = "Bubble grid registration markers could not be identified."


def marker_centres(gray):
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 31, 15,
    )
    contours = sorted(cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0],
                      key=cv2.contourArea, reverse=True)
    markers = []
    for contour in contours:
        area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)
        quad = cv2.approxPolyDP(contour, perimeter * 0.04, True)
        x, y, w, h = cv2.boundingRect(contour)
        if not (len(quad) == 4 and cv2.isContourConvex(quad)
                and 5 <= w <= min(gray.shape) * .03
                and 5 <= h <= min(gray.shape) * .03
                and .7 < w / h < 1.4 and area / (w * h) > .6
                and binary[y:y+h, x:x+w].mean() / 255 > .4):
            continue
        point = np.array([x + w / 2, y + h / 2], dtype=np.float32)
        if any(np.linalg.norm(point - item[0]) < max(w, h) * .7 for item in markers):
            continue
        markers.append((point, (w + h) / 2))
    return markers


def samples(gray, template, ring=False):
    values = np.zeros((template.columns, template.rows))
    yy, xx = np.mgrid[-16:17, -16:17]
    radius = np.sqrt(xx ** 2 + (yy / template.radius_y_scale) ** 2)
    mask = ((radius >= 11.5) & (radius <= 14.5)) if ring else radius <= 9
    for column in range(template.columns):
        x = round((template.first_x + column * template.pitch_x) * (WIDTH - 1))
        for digit in range(template.rows):
            y = round((template.first_y + digit * template.pitch_y) * (HEIGHT - 1))
            patch = gray[y-16:y+17, x-16:x+17].astype(float)
            # Local white level tolerates slow lighting gradients and shadows.
            background = max(30., np.percentile(patch, 95))
            ink = np.clip((background - patch) / background, 0, 1)
            values[column, digit] = ink[mask].mean()
    return values


def locate_grid(gray):
    markers = marker_centres(gray)
    if len(markers) > 45:
        return None  # Bound combinatorial work on adversarial/noisy documents.
    candidates = []
    destination = np.float32([[0, 0], [WIDTH-1, 0], [WIDTH-1, HEIGHT-1], [0, HEIGHT-1]])
    seen = set()
    for group in combinations(markers, 4):
        sizes = [item[1] for item in group]
        if max(sizes) / min(sizes) > 1.8:
            continue
        points = cv2.convexHull(np.float32([item[0] for item in group])).reshape(-1, 2)
        if len(points) != 4:
            continue
        edges = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
        if not (.65 < edges[0] / edges[2] < 1.55 and .65 < edges[1] / edges[3] < 1.55):
            continue
        for shift in range(4):
            quad = np.roll(points, shift, axis=0)
            u, v = quad[1] - quad[0], quad[3] - quad[0]
            width, height = np.linalg.norm(u), np.linalg.norm(v)
            size = np.mean(sizes)
            if not (.43 < width / height < .86 and 12 < width / size < 35
                    and 18 < height / size < 60
                    and abs(np.dot(u, v) / (width * height)) < .45):
                continue
            # ConvexHull ordering is consistent but may run counterclockwise.
            if (u[0] * v[1] - u[1] * v[0]) < 0:
                quad = quad[[1, 0, 3, 2]]
            key = tuple(quad.flatten())
            if key in seen:
                continue
            seen.add(key)
            matrix = cv2.getPerspectiveTransform(quad, destination)
            rectified = cv2.warpPerspective(gray, matrix, (WIDTH, HEIGHT), borderValue=255)
            for template in TEMPLATES:
                rings = samples(rectified, template, ring=True)
                coverage = float(np.mean(rings > .10))
                if coverage >= .93:
                    candidates.append((coverage + float(np.mean(rings)) * .1,
                                       quad, rectified, template))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best = candidates[0]
    # Distinct plausible grids/frames must not silently select a student.
    for other in candidates[1:]:
        different_frame = np.max(np.linalg.norm(best[1] - other[1], axis=1)) > 10
        uncertain_template = best[3].version != other[3].version and abs(best[0] - other[0]) < .035
        if different_frame or uncertain_template:
            return None
    return best[1:]


def read_bubbles(image_path):
    original = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if original is None:
        return BubbleReading(reason="The image could not be decoded.")
    scale = min(1., 1800 / max(original.shape))
    gray = cv2.resize(original, None, fx=scale, fy=scale) if scale < 1 else original
    grid = locate_grid(gray)
    if grid is None:
        return BubbleReading()
    quad, rectified, template = grid
    densities = samples(rectified, template)
    # Most cells are unfilled; global baseline also works for 00000000.
    baseline = float(np.median(densities))
    scores = np.clip(densities - baseline, 0, 1)
    columns, ambiguity, digits, margins = [], [], [], []
    for index, column in enumerate(scores):
        order = np.argsort(column)[::-1]
        top, second = float(column[order[0]]), float(column[order[1]])
        margin = top - second
        reason = None
        if np.count_nonzero(column >= CLEAR_FILL) > 1:
            reason = "multiple"
        elif top < POSSIBLE_FILL:
            reason = "empty"
        elif top < CLEAR_FILL or margin < MIN_MARGIN or second >= POSSIBLE_FILL:
            reason = "unreadable"
        digit = None if reason else int(order[0])
        columns.append({"column": index + 1, "scores": [round(float(s), 4) for s in column],
                        "digit": digit, "margin": round(margin, 4), "reason": reason})
        digits.append("X" if digit is None else str(digit))
        if reason:
            ambiguity.append({"column": index + 1, "reason": reason})
        margins.append(margin)
    points = quad / scale
    x, y = points.min(axis=0)
    right, bottom = points.max(axis=0)
    region = {"page": 0, "x": float(x), "y": float(y), "width": float(right-x),
              "height": float(bottom-y), "image_width": original.shape[1],
              "image_height": original.shape[0], "corners": points.tolist(),
              "rectified_width": WIDTH, "rectified_height": HEIGHT}
    image = cv2.imencode('.png', rectified)[1].tobytes()
    return BubbleReading("".join(digits), columns, ambiguity, region, template.version,
                         image, min(margins), "Ambiguous bubbles require manual verification." if ambiguity else "")
