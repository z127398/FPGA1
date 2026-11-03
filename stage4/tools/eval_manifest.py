"""Evaluate traffic-light or lane labels from a CSV manifest.

Traffic-light manifest columns: path,label
  label in RED/GREEN/YELLOW/NONE

Lane manifest columns: path,left,right
  side labels in SOLID/DASHED/NONE

This keeps dataset-specific download/annotation outside the runtime and makes
the reported numbers reproducible from a recorded manifest.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import cv2

from perception import LaneDetector, TrafficLightDetector


def _read_image(path, size):
    img = cv2.imread(str(path))
    if img is not None and size is not None:
        img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
    return img


def eval_tl(rows, root, size=None):
    det = TrafficLightDetector(vote_n=1)
    total = 0
    correct = 0
    confusion = Counter()
    for row in rows:
        path = Path(root) / row["path"]
        img = _read_image(path, size)
        if img is None:
            print("MISSING", path)
            continue
        expected = row["label"].strip().upper()
        got = det.detect(img).state
        total += 1
        correct += int(got == expected)
        confusion[(expected, got)] += 1
    summary = {
        "kind": "traffic_light",
        "total": total,
        "correct": correct,
        "accuracy": (correct / total) if total else 0.0,
        "confusion": [
            {"expected": expected, "predicted": got, "count": n}
            for (expected, got), n in sorted(confusion.items())
        ],
    }
    print("TL total", total, "correct", correct,
          "accuracy", summary["accuracy"])
    for (expected, got), n in sorted(confusion.items()):
        print("  %-7s -> %-7s %d" % (expected, got, n))
    return summary


def eval_lane(rows, root, size=None):
    total = 0
    correct = 0
    confusion = Counter()
    for row in rows:
        path = Path(root) / row["path"]
        img = _read_image(path, size)
        if img is None:
            print("MISSING", path)
            continue
        # Manifest rows are independent images from different clips.  Reset
        # sequence tracking between rows so one clip cannot bias the next.
        det = LaneDetector(vote_n=1)
        result = det.detect(img)
        for side, expected in (("left", row["left"].strip().upper()),
                               ("right", row["right"].strip().upper())):
            got = getattr(result, side + "_state")
            total += 1
            correct += int(got == expected)
            confusion[(side, expected, got)] += 1
    summary = {
        "kind": "lane",
        "sides": total,
        "correct": correct,
        "accuracy": (correct / total) if total else 0.0,
        "confusion": [
            {
                "side": side,
                "expected": expected,
                "predicted": got,
                "count": n,
            }
            for (side, expected, got), n in sorted(confusion.items())
        ],
    }
    print("LANE samples", total, "correct", correct,
          "accuracy", summary["accuracy"])
    for (side, expected, got), n in sorted(confusion.items()):
        print("  %-5s %-7s -> %-7s %d" % (side, expected, got, n))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=("tl", "lane"))
    ap.add_argument("manifest")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json-out")
    ap.add_argument(
        "--size",
        help="optional WIDTHxHEIGHT resize matching the runtime input",
    )
    args = ap.parse_args()
    with open(args.manifest, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    size = None
    if args.size:
        width, height = args.size.lower().split("x", 1)
        size = (int(width), int(height))
    if args.kind == "tl":
        summary = eval_tl(rows, args.root, size)
    else:
        summary = eval_lane(rows, args.root, size)
    summary["manifest"] = str(args.manifest)
    summary["root"] = str(args.root)
    summary["input_size"] = list(size) if size else None
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
