# Reusable FPGA and Vision Skills

This directory contains workflow patterns extracted from the ADAS Stage 4
project. Each item documents when it applies, how to verify it, and how it
fails so another team can use it without copying the whole application.

| Skill | Reusable value | Entry point |
|---|---|---|
| `pynq-safe-frame-pipeline` | Frame-driven VDMA pipeline with explicit register contracts and safe recovery | `pynq-safe-frame-pipeline/README.md` |
| `vision-evidence-bench` | Repeatable FPS and latency evidence from runtime CSV data | `vision-evidence-bench/README.md` |
| `debug-playbooks` | Symptom-to-cause playbooks for GPIO masks, VDMA, display colour and duplicate tests | `debug-playbooks/README.md` |
| `llm-workflows` | Prompts for hardware/software partitioning and evidence-based debugging | `llm-workflows/README.md` |

## Common rules

- Confirm the hardware target and artifact hash before interpreting software
  measurements.
- Keep the FPGA control and status contracts explicit and versioned.
- Separate unsupported claims from measured results.
- Restore a quiet known-good bitstream after every interactive hardware test.
- Keep raw logs and source CSV files beside generated summaries.

These skills are not limited to traffic-light, lane or obstacle perception.
They apply to any Zynq/PYNQ system that streams frames through VDMA and must
fail safely when the PS processing loop stops.
