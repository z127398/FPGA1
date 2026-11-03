"""A/B benchmark PS grayscale conversion versus the PL grayscale path."""

import json
import time
from pathlib import Path

from overlay import AdasOverlay


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "lane_input_bench.json"


def _measure(adas, input_mode, duration):
    started = time.time()
    last_fps = adas.run_osd(
        mode="lane", duration=duration, input_mode=input_mode
    )
    elapsed = time.time() - started
    status = adas.read_status()
    perception = adas.last_perception
    lanes = getattr(perception, "lanes", None)
    return {
        "input_mode": input_mode,
        "elapsed_s": elapsed,
        "fps_average": adas.last_run_fps,
        "fps_last_window": last_fps,
        "status": status,
        "last_error": repr(adas.last_error),
        "lane": {
            "left": getattr(lanes, "left_state", "NONE"),
            "right": getattr(lanes, "right_state", "NONE"),
            "coverage_left": getattr(lanes, "coverage_left", 0.0),
            "coverage_right": getattr(lanes, "coverage_right", 0.0),
        },
    }


def main():
    adas = AdasOverlay()
    result = {"duration_s": 20.0, "prepare_s": 10.0, "ok": False}
    try:
        adas.start()
        adas.start_passthrough(0)
        time.sleep(result["prepare_s"])
        # Warm the camera and discard the one-frame colour/grey switch tear.
        adas.run_osd(mode="lane", duration=3.0, input_mode="color")
        result["color"] = _measure(adas, "color", result["duration_s"])
        result["gray"] = _measure(adas, "gray", result["duration_s"])
        color_fps = result["color"]["fps_average"]
        gray_fps = result["gray"]["fps_average"]
        result["gray_delta_pct"] = (
            (gray_fps - color_fps) / color_fps * 100.0
            if color_fps > 0 else None
        )
        result["ok"] = all(
            item["last_error"] == "None" and
            item["status"].get("wd_timeout") == 0 and
            item["lane"]["left"] == "SOLID" and
            item["lane"]["right"] == "SOLID"
            for item in (result["color"], result["gray"])
        )
        return 0 if result["ok"] else 1
    finally:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
