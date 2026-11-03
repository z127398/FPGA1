"""Restore the quiet Stage 2 bitstream after an interrupted hardware test."""

from overlay import AdasOverlay


def main() -> int:
    AdasOverlay().restore_quiet_bitstream()
    print("stage2 restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
