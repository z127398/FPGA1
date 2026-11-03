# LLM Workflows for FPGA/Vision Engineering

## Hardware/software partitioning prompt

Use this prompt with the actual interfaces and measured constraints:

```text
Here is an FPGA/Zynq application with these clocks, interfaces and data rates.
Propose PL/PS partitions. For each partition give latency, memory traffic,
resource cost and verification method. Reject any proposal that requires
unmeasured assumptions. Ask for missing data instead of inventing values.
```

Record the proposed partition, the engineer's decision and the measurement
that justified the decision.

## Evidence-based debugging prompt

```text
Do not change configuration yet. From the attached register dump, test output
and image, list the three most likely causes. For each cause, give one
read-only diagnostic and one discriminating expected result.
```

This prevents the common failure mode of changing several thresholds or
hardware settings simultaneously.

## Report audit prompt

```text
Compare these report claims against the raw CSV/JSON evidence. Mark each claim
as VERIFIED, CONFLICTING or UNSUPPORTED. Do not infer missing measurements.
Propose the smallest correction for each conflicting claim.
```

## Rules for a reusable collaboration record

- Preserve the human prompt and selected model output.
- Record the human verification result and any rejected suggestion.
- Do not use model agreement as evidence.
- Do not publish private hidden reasoning; publish decisions, outputs and
  reproducible checks.
