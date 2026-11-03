"""Measure the zero-copy PL camera-to-LCD passthrough rate."""

import json
import sys
from pathlib import Path

from overlay import AdasOverlay


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "passthrough.json"


def main(duration=10.0):
    adas = AdasOverlay()
    result = {"duration_s": duration, "ok": False}
    try:
        adas.start()
        result["fps"] = adas.measure_passthrough_fps(duration)
        result["ok"] = result["fps"] > 0
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
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    raise SystemExit(main(duration))
