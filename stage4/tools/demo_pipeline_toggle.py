"""Show live color, PL-gray and restored color frames on the LCD."""

import asyncio
import json
import time
from pathlib import Path

import cv2
import numpy as np

from overlay import AdasOverlay


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "pipeline_modes"


def _copy_frame(adas, timeout=1.0):
    loop = asyncio.get_event_loop()
    frame = loop.run_until_complete(
        asyncio.wait_for(adas.video_in.readframe_async(), timeout)
    )
    return np.array(frame, copy=True)


def _save(path, frame):
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError("failed to write %s" % path)
    means = np.asarray(frame, dtype=np.float32).reshape(-1, 3).mean(axis=0)
    return [round(float(value), 2) for value in means]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    adas = AdasOverlay()
    result = {"ok": False, "color_seconds": 6.0, "gray_seconds": 6.0}
    try:
        adas.start()
        adas.video_in.tie(adas.video_out)
        adas.set_pipeline("color")
        time.sleep(result["color_seconds"])
        color = _copy_frame(adas)
        result["color_bgr_mean"] = _save(OUT / "color.png", color)

        adas.set_pipeline("gray")
        time.sleep(result["gray_seconds"])
        gray = _copy_frame(adas)
        result["gray_bgr_mean"] = _save(OUT / "gray.png", gray)

        adas.set_pipeline("color")
        time.sleep(result["color_seconds"])
        restored = _copy_frame(adas)
        result["restored_bgr_mean"] = _save(
            OUT / "color_restored.png", restored
        )
        result["ok"] = True
        return 0
    finally:
        (ROOT / "evidence" / "pipeline_toggle.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
