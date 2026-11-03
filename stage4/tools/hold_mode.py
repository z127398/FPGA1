"""Hold one perception mode until interrupted."""

import sys

from overlay import AdasOverlay


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "traffic_light"
    input_mode = sys.argv[2] if len(sys.argv) > 2 else None
    if mode not in ("traffic_light", "lane", "obstacle"):
        raise SystemExit("mode must be traffic_light, lane or obstacle")
    adas = AdasOverlay()
    try:
        adas.start()
        adas.run_osd(
            mode=mode, duration=86400.0, input_mode=input_mode
        )
    except KeyboardInterrupt:
        pass
    finally:
        adas.stop()
        adas.restore_quiet_bitstream()
        print("%s stopped; stage2 restored" % mode, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
