"""Run a timed OSD soak test and log FPS, RSS and board temperature."""

import json
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
OUT = ROOT / "evidence" / "soak"


def rss_kb():
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except Exception:
        pass
    return -1


def temperature_c():
    for path in ("/sys/class/thermal/thermal_zone0/temp",
                 "/sys/class/thermal/thermal_zone1/temp"):
        try:
            return int(Path(path).read_text().strip()) / 1000.0
        except Exception:
            pass
    return None


def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    interval = 30.0
    OUT.mkdir(parents=True, exist_ok=True)
    log_path = OUT / "soak.jsonl"
    summary_path = OUT / "summary.json"
    adas = AdasOverlay()
    start = time.time()
    samples = []
    try:
        adas.start()
        adas._set_heartbeat_mode("frame")
        adas.video_out.writeframe(to_lcd(np.zeros((480, 800, 3), dtype=np.uint8)))
        mode = "traffic_light"
        pipeline = PerceptionPipeline(mode=mode)
        engine = DecisionEngine(mode=mode)
        with log_path.open("w", encoding="utf-8") as fh:
            last_log = 0.0
            frame_idx = 0
            count = 0
            t_fps = time.time()
            while time.time() - start < minutes * 60.0:
                frame = adas.video_in.readframe()
                bgr = cv2.resize(
                    frame, adas.proc_size, interpolation=cv2.INTER_NEAREST
                )
                result = pipeline.process(bgr, frame_idx)
                decision = engine.step(result, adas.read_btns())
                adas.write_dec(decision.tl_state, decision.lane_left,
                               decision.lane_right, decision.obstacle,
                               decision.force, decision.turn,
                               feed_heartbeat=True)
                status = adas.read_status()
                out = compose(
                    bgr, result, decision, status, adas.fps, mode=mode
                )
                adas.video_out.writeframe(to_lcd(out))
                frame_idx += 1
                count += 1
                now = time.time()
                if now - t_fps >= 1.0:
                    adas.fps = count / (now - t_fps)
                    count = 0
                    t_fps = now
                if now - start - last_log < interval:
                    continue
                last_log = now - start
                row = {
                    "elapsed_s": round(time.time() - start, 1),
                    "fps": round(adas.fps, 2),
                    "rss_kb": rss_kb(),
                    "temp_c": temperature_c(),
                    "status": status,
                    "error": repr(adas.last_error),
                }
                samples.append(row)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                print(json.dumps(row, ensure_ascii=False), flush=True)
        summary = {
            "minutes": minutes,
            "samples": len(samples),
            "fps_min": min((s["fps"] for s in samples), default=0),
            "fps_max": max((s["fps"] for s in samples), default=0),
            "fps_mean": (sum(s["fps"] for s in samples) / len(samples)
                         if samples else 0),
            "rss_start_kb": samples[0]["rss_kb"] if samples else -1,
            "rss_end_kb": samples[-1]["rss_kb"] if samples else -1,
            "temp_max_c": max((s["temp_c"] for s in samples
                               if s["temp_c"] is not None), default=None),
            "last_error": samples[-1]["error"] if samples else None,
        }
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("SUMMARY", summary, flush=True)
    finally:
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored", flush=True)


if __name__ == "__main__":
    main()
