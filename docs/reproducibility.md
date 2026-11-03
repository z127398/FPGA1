# Reproduction Guide

## Verified environment

| Component | Verified version |
|---|---|
| Board | ALIENTEK ZYNQ-7010, `7z010clg400-1` |
| Board image | PYNQ 2.7 on PynqLinux/Ubuntu 20.04 |
| Kernel | `5.4.0-xilinx-v2020.2` |
| Python | 3.8.2 |
| NumPy | 1.20.3 |
| OpenCV | Ubuntu `libopencv-*` 4.2.0 |
| pytest | 4.6.9 |
| PYNQ | 2.7.0 |
| Vivado | 2020.2 |

The competition guide recommends Vivado/Vitis 2025.2 or 2026.1. This project
uses 2020.2 because it targets the supplied PYNQ 2.7 image and the existing
XC7Z010 board. All checked-in Tcl scripts and reports are provided so the older
tool version can be audited and reproduced. No newer-tool compatibility is
claimed.

## Bitstream

Verified application artifact:

```text
release/stage4/ov5640_rgb2gray.bit
SHA-256 6DDB269BB297D2A69BE4C63FF53BC823ECAB9B1D021C2EC908C377A2B92E1066
MD5     1f18cca001db496408ec85ec9cb301ea
```

The standard PYNQ Stage 2 bitstream is restored after every hardware test to
leave the board quiet and prevent a stale watchdog from sounding.

## Deploy

Copy the repository's `stage4` directory to:

```text
/home/xilinx/jupyter_notebooks/stage4
```

Copy `release/stage4/ov5640_rgb2gray.bit` and `.hwh` to:

```text
/home/xilinx/jupyter_notebooks/stage4_ready/
```

The quiet Stage 2 bitstream is expected at:

```text
/home/xilinx/jupyter_notebooks/ready_to_test/ov5640_rgb2gray.bit
```

## Install dependencies

Do not replace the PYNQ image packages blindly. Confirm the versions first:

```bash
/usr/local/share/pynq-venv/bin/python3 --version
/usr/local/share/pynq-venv/bin/python3 -m pip show numpy pytest pynq
dpkg -l | grep opencv
```

Desktop report/test dependencies are listed in `requirements-dev.txt`.
The verified board dependency inventory is in `requirements-board.txt`.

## Run tests

Run the declared suite explicitly. Older test copies may remain in the root of
an existing board installation and otherwise cause a pytest import mismatch:

```bash
cd /home/xilinx/jupyter_notebooks/stage4
PYTHONPATH=. /usr/local/share/pynq-venv/bin/python3 -m pytest -q \
  tests/test_cards.py tests/test_overlay.py \
  tests/test_decision.py tests/test_perception.py
```

Expected result for this frozen source tree: `45 passed`.

## Hardware checks

Use `sudo env` so `PYTHONPATH` survives sudo:

```bash
cd /home/xilinx/jupyter_notebooks/stage4
sudo env XILINX_XRT=/usr PYTHONPATH="$PWD" \
  /usr/local/share/pynq-venv/bin/python3 tools/smoke_modes.py
```

Interactive lane geometry test:

```bash
sudo env XILINX_XRT=/usr PYTHONPATH="$PWD" \
  /usr/local/share/pynq-venv/bin/python3 tools/smoke_lane_geometry.py AUTO
```

The operator centres one SOLID or DASHED card, moves it horizontally until the
LCD shows `DEPART`, holds the alarm for confirmation, then centres it again
until the alarm clears. Diagnostics and evidence are written under
`stage4/evidence/lane_geometry/`.

Obstacle-only test:

```bash
sudo env XILINX_XRT=/usr PYTHONPATH="$PWD" \
  /usr/local/share/pynq-venv/bin/python3 tools/retest_lane_obstacle.py \
  --obstacle-only
```

Keep hands out of the background-learning frame, place a static object in the
lower centre, remove hands after placement, then remove the object and verify
that `boxes=[]`, `present=false` and `alarm_reason=0`.

Emergency restoration after an interrupted hardware run:

```bash
sudo env XILINX_XRT=/usr PYTHONPATH="$PWD" \
  /usr/local/share/pynq-venv/bin/python3 tools/restore_safe.py
```

## Rebuild

The build is scripted under `scripts/`. Use Vivado 2020.2 batch mode and the
Stage 3 scripts to recreate the pipeline and decision FSM. The checked-in
timing and utilization reports provide the expected acceptance point:

- WNS `+0.757 ns`, TNS `0`, all timing constraints met;
- LUT `9739 / 17600` (`55.34%`);
- FF `16564 / 35200` (`47.06%`);
- BRAM tile `10 / 60` (`16.67%`);
- DSP `3 / 80` (`3.75%`).

Rebuild output must reproduce the exported bitstream and HWH before treating a
resource or FPS comparison as equivalent.
