"""Reproducible held-out synthetic evaluation; never contains real identities."""

import argparse
import json
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory

from submissions.recognition.bubbles import read_bubbles
from submissions.tests.bubble_helpers import bubble_image, distorted_image


def evaluate(seed=729163, count=64):
    random = Random(seed)
    transformations = [
        {},
        {"angle": 7},
        {"angle": 90},
        {"angle": 180},
        {"angle": 270},
        {"perspective": True},
        {"shadow": True},
        {"scale": 0.75},
    ]
    exact = false_clear = rejected = unsafe_ambiguous = 0
    with TemporaryDirectory() as directory:
        path = Path(directory) / "heldout.png"
        for index in range(count):
            number = "".join(str(random.randrange(10)) for _ in range(8))
            image = distorted_image(
                bubble_image(number, compact=bool(index % 2)),
                **transformations[(index // 2) % len(transformations)],
            )
            image.save(path)
            reading = read_bubbles(path)
            if reading.candidate == number:
                exact += 1
            elif reading.candidate and "X" not in reading.candidate:
                false_clear += 1
            else:
                rejected += 1
        # Independent negative cases: one blank, two fills, faint mark and erasure.
        for index in range(32):
            number = "".join(str(random.randrange(10)) for _ in range(8))
            fills = {column: [int(number[column])] for column in range(8)}
            column = random.randrange(8)
            kind = index % 4
            shade = 0
            if kind == 0:
                fills[column] = []
            elif kind in (1, 3):
                fills[column].append((int(number[column]) + 3) % 10)
                shade = 160 if kind == 3 else 0
            else:
                shade = 205
            bubble_image(
                number, compact=bool(index % 2), fills=fills, shade=shade
            ).save(path)
            reading = read_bubbles(path)
            if reading.candidate and not reading.ambiguity:
                unsafe_ambiguous += 1
    return {
        "dataset": "held-out synthetic; not physical scans",
        "seed": seed,
        "clear_samples": count,
        "exact": exact,
        "manual_review": rejected,
        "exact_number_accuracy": exact / count,
        "false_clear_readings": false_clear,
        "false_clear_read_rate": false_clear / count,
        "ambiguous_samples": 32,
        "unsafe_clear_readings_on_ambiguous": unsafe_ambiguous,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=729163)
    parser.add_argument("--count", type=int, default=64)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    print(json.dumps(evaluate(args.seed, args.count), indent=2))
