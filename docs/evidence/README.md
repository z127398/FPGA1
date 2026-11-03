# Evidence Index

Final evidence is grouped by function instead of duplicated at the directory
root.

| Path | Contents |
|---|---|
| `printed_20261102/` | current technical-report red/green/yellow, solid/dashed, departure and obstacle captures |
| `red/`、`green/`、`yellow/` | earlier traffic-light evidence retained for traceability |
| `count_red.json`、`count_green.json`、`count_yellow.json` | 20-frame card counters |
| `lane_type_tuning/` | earlier SOLID 12/12 and DASHED 12/12 evidence |
| `lane_geometry/` | earlier centred, departure, alarm and cleared evidence |
| `lane_geometry.json` | lane alarm summary and register values |
| `lane_input_bench.json` | PL grayscale versus PS grayscale benchmark |
| `latency_traffic_light.csv` | traffic-light per-frame latency |
| `latency_lane.csv` | lane per-frame latency |
| `latency_obstacle.csv` | obstacle per-frame latency |
| `pipeline_modes/` | software-triggered colour/gray/restored-colour frames |
| `environment/` | earlier static-object NEAR evidence |
| `safety/` | palette, mode isolation, video selector and watchdog evidence |
| `soak/` | earlier long-run stability evidence |

## Regenerate

On the board:

```bash
cd /home/xilinx/jupyter_notebooks/stage4
sudo env XILINX_XRT=/usr PYTHONPATH="$PWD" \
  /usr/local/share/pynq-venv/bin/python3 tools/smoke_modes.py
```

- `tools/bench_passthrough.py` records PL passthrough FPS.
- `tools/bench_latency.py <mode>` records per-frame latency.
- `tools/bench_lane_input.py` compares color and PL-gray lane input.
- `tools/smoke_lane_geometry.py AUTO` records departure and recovery.
- `tools/tune_lane_type.py` records live SOLID/DASHED feature distributions.
- `tools/environment_capture.py` records static-object evidence.

Pull generated files back before shutting down. The board is restored to the
quiet Stage 2 bitstream after every hardware test.
