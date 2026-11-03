# Vision Evidence Bench

## Purpose

Turn raw per-frame runtime measurements into reproducible summary statistics.
The workflow is independent of the vision algorithm and can be used for any
CSV where each row is one processed frame.

## Input

The CSV should contain numeric columns such as:

```text
frame,read_ms,process_ms,osd_ms,write_ms,total_ms
```

The Stage 4 collector is `stage4/tools/bench_latency.py`.

## Usage

```bash
python3 summarize_latency.py evidence/latency.csv
python3 summarize_latency.py evidence/latency.csv --json
```

Report mean, P95 and maximum for end-to-end latency. Also report throughput,
the number of frames, processing resolution and the loaded bitstream hash.
FPS alone is not a latency measurement.

## Acceptance template

- Warm up the camera until automatic exposure and white balance settle.
- Record the actual processing resolution and output resolution.
- Record the bitstream hash and software versions.
- Keep the raw CSV; generated summaries must be traceable to it.
- Separate controlled-card evidence from dataset or road-scene evidence.

## Failure conditions

- Comparing FPS from different resolutions.
- Reporting a single best frame instead of distribution statistics.
- Calling host-side processing time "glass-to-glass latency".
- Updating the report after changing code without regenerating the CSV.
