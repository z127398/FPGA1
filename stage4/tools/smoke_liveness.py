"""Verify frame-driven heartbeat, PS stall injection and PL watchdog recovery."""

import json
import sys
from pathlib import Path

from overlay import AdasOverlay


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "watchdog_smoke.json"


def main() -> int:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    stall_after = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    stall_duration = float(sys.argv[3]) if len(sys.argv) > 3 else 1.5
    adas = AdasOverlay()
    result = {
        "duration_s": duration,
        "stall_after_s": stall_after,
        "stall_duration_s": stall_duration,
    }
    try:
        adas.start()
        adas.start_watchdog_monitor(str(OUT))
        result["fps"] = adas.run_osd(
            duration=duration,
            stall_after=stall_after,
            stall_duration=stall_duration,
        )
        result["events"] = adas._watchdog_events
        result["final_status"] = adas.read_status()
        values = [event["wd_timeout"] for event in result["events"]]
        result["ok"] = (
            adas.last_error is None
            and 1 in values
            and values[-1] == 0
        )
        return 0 if result["ok"] else 1
    except BaseException as exc:
        result["exception"] = repr(exc)
        return 1
    finally:
        adas.stop_watchdog_monitor()
        OUT.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
