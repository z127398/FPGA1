"""Count live detections over N frames for one target card."""

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from osd import to_lcd
from overlay import AdasOverlay
from perception import LaneDetector, TrafficLightDetector


ROOT = Path(__file__).resolve().parents[1]


def main():
    target = (sys.argv[1] if len(sys.argv) > 1 else "RED").upper()
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    out = ROOT / "evidence" / ("count_" + target.lower() + ".json")
    adas = AdasOverlay()
    try:
        adas.start()
        adas.video_out.writeframe(to_lcd(np.zeros((480, 800, 3), dtype=np.uint8)))
        tl = TrafficLightDetector(vote_n=1)
        lane = LaneDetector(vote_n=1)
        states = []
        deadline = time.time() + 10.0
        found = False
        while time.time() < deadline:
            frame = adas.video_in.readframe()
            bgr = cv2.resize(frame, adas.proc_size, interpolation=cv2.INTER_NEAREST)
            if target in ("RED", "GREEN", "YELLOW"):
                s = tl.detect(bgr).state
                hit = s == target
            else:
                r = lane.detect(bgr)
                s = (r.left_state, r.right_state)
                hit = s == (target, target)
            if hit:
                states.append(s)
                found = True
                break
        if not found:
            print("TIMEOUT waiting for", target)
            return
        for _ in range(n - 1):
            frame = adas.video_in.readframe()
            bgr = cv2.resize(frame, adas.proc_size, interpolation=cv2.INTER_NEAREST)
            if target in ("RED", "GREEN", "YELLOW"):
                states.append(tl.detect(bgr).state)
            else:
                r = lane.detect(bgr)
                states.append((r.left_state, r.right_state))
        if target in ("RED", "GREEN", "YELLOW"):
            hits = sum(1 for s in states if s == target)
        else:
            hits = sum(1 for s in states if s == (target, target))
        meta = {"target": target, "frames": n, "hits": hits,
                "states": states}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print("%s: %d/%d" % (target, hits, n))
        print("states", states)
    finally:
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored")


if __name__ == "__main__":
    main()
