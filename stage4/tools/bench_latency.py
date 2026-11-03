"""Measure per-frame read/process/OSD/write latency on the board."""

import asyncio
import csv
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from decision import DecisionEngine
from osd import compose, to_lcd
from overlay import AdasOverlay
from perception import PerceptionPipeline


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence"


def percentile(values, q):
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def main(n=100):
    OUT.mkdir(parents=True, exist_ok=True)
    adas = AdasOverlay()
    rows = []
    try:
        adas.start()
        loop = asyncio.get_event_loop()
        adas.video_out.writeframe(to_lcd(np.zeros((480, 800, 3), dtype=np.uint8)))
        mode = sys.argv[1] if len(sys.argv) > 1 else "traffic_light"
        pipe = PerceptionPipeline(mode=mode)
        engine = DecisionEngine(mode=mode)
        for i in range(n):
            t0 = time.perf_counter()
            try:
                frame = loop.run_until_complete(
                    asyncio.wait_for(adas.video_in.readframe_async(), 1.0)
                )
            except asyncio.TimeoutError:
                continue
            t1 = time.perf_counter()
            bgr = cv2.resize(frame, adas.proc_size, interpolation=cv2.INTER_NEAREST)
            result = pipe.process(bgr, i)
            decision = engine.step(result, adas.read_btns())
            adas.write_dec(
                decision.tl_state, decision.lane_left, decision.lane_right,
                decision.obstacle, decision.force, decision.turn,
                feed_heartbeat=True,
            )
            t2 = time.perf_counter()
            out = compose(
                bgr, result, decision, adas.read_status(), adas.fps,
                mode=mode,
            )
            t3 = time.perf_counter()
            loop.run_until_complete(
                asyncio.wait_for(
                    adas.video_out.writeframe_async(to_lcd(out)), 1.0
                )
            )
            t4 = time.perf_counter()
            rows.append({
                "frame": i,
                "read_ms": (t1 - t0) * 1000.0,
                "process_ms": (t2 - t1) * 1000.0,
                "osd_ms": (t3 - t2) * 1000.0,
                "write_ms": (t4 - t3) * 1000.0,
                "total_ms": (t4 - t0) * 1000.0,
            })
        if not rows:
            raise RuntimeError("no camera frames captured")
        path = OUT / ("latency_%s.csv" % mode)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        for key in ("read_ms", "process_ms", "osd_ms", "write_ms", "total_ms"):
            vals = [r[key] for r in rows]
            print("%-11s mean=%7.1f p95=%7.1f max=%7.1f"
                  % (key, np.mean(vals), percentile(vals, 95), max(vals)))
        print("wrote", path)
    finally:
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored")


if __name__ == "__main__":
    main()
