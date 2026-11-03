"""Hold the lane OSD mode until the process is interrupted."""


def main() -> int:
    from overlay import AdasOverlay

    adas = AdasOverlay()
    try:
        adas.start()
        adas.run_osd(mode="lane", duration=86400.0)
    except KeyboardInterrupt:
        pass
    finally:
        adas.stop()
        adas.restore_quiet_bitstream()
        print("lane mode stopped; stage2 restored", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
