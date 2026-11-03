"""Check colour/grey selection and display a labelled LCD colour-bar test."""

import json
import sys
import time
from pathlib import Path

from overlay import AdasOverlay


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "video_probe.json"


def main() -> int:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    adas = AdasOverlay()
    result = {}
    try:
        adas.start()
        result = adas.probe_video_modes()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        adas.show_color_bars()
        time.sleep(duration)
        return 0 if result.get("color_pass") else 1
    finally:
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
