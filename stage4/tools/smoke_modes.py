"""Run the three strict perception modes and save FPS/status evidence."""

import json
from pathlib import Path

from overlay import AdasOverlay


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "modes_smoke.json"


def main() -> int:
    adas = AdasOverlay()
    result = {"modes": {}, "ok": False}
    try:
        adas.start()
        for mode in ("traffic_light", "lane", "obstacle"):
            result["modes"][mode] = {
                "fps": adas.run_osd(mode=mode, duration=20.0),
                "status": adas.read_status(),
                "last_error": repr(adas.last_error),
            }
        result["ok"] = all(
            value["last_error"] == "None" and
            value["status"].get("wd_timeout") == 0
            for value in result["modes"].values()
        )
        return 0 if result["ok"] else 1
    except BaseException as exc:
        result["exception"] = repr(exc)
        return 1
    finally:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
