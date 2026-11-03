# Large-Model Collaboration Record

This record keeps selected prompts, model recommendations, engineering
decisions and reproducible verification. It intentionally excludes private
hidden reasoning. A model response was never treated as evidence until it was
checked with a test, register dump or board capture.

## Case 1: stage decomposition and open-ended plan

**Human prompt**

> The project must become a credible AMD FPGA competition entry rather than a
> toy. Propose the remaining engineering path and distinguish measured results
> from assumptions.

**Selected model output**

- Keep the existing camera-to-PL-to-VDMA-to-PS-to-LCD chain.
- Split perception into mutually exclusive traffic-light, lane and obstacle
  modes.
- Add a measurable safety feature that remains active when PS processing
  stops.
- Require screenshots, status JSON and raw timing data for every claim.

**Decision and correction**

The proposal was accepted, but later model suggestions to rebuild PL for Sobel
or add YOLO were rejected because neither had a board benchmark or fit the
freeze window.

**Verification**

The register contract, mode isolation and watchdog behaviour were exercised on
the board. The hardware control word remains unchanged.

## Case 2: LCD red/blue inversion

**Human prompt**

> Red is displayed as blue and blue as yellow, but recognition is still
> correct. Diagnose the display path without changing the detector.

**Selected model output**

Separate perception colour ordering from framebuffer colour ordering. First
test with colour bars and three-channel means; only then change the LCD write
conversion.

**Decision and correction**

Human confirmation showed the detector was correct. The display path was fixed
by retaining OpenCV BGR order at the LCD frontend. The operator then confirmed
red and blue were correct.

**Verification**

Colour-bar evidence and channel statistics are stored under
`docs/evidence/safety/`; the detector thresholds were not changed to compensate
for a display bug.

## Case 3: traffic lights must be circular

**Human prompt**

> Colour alone is insufficient. At minimum the object should be circular before
> it is classified as a traffic light. Research a practical approach.

**Selected model output**

Use an HSV candidate mask followed by contour shape gates: circularity,
convexity and ellipse inertia ratio. Keep a multi-frame state vote to reject
single-frame colour flashes.

**Decision and correction**

The shape gate was implemented with explicit limits and negative tests. Arrow
lights were declared unsupported rather than silently lowering the circularity
standard.

**Verification**

The card suite and BSTLD held-out subset were rerun. Rectangle and coloured
non-lamp negatives are rejected; the limitation is documented in the report.

## Case 4: lane geometry with no PL rebuild

**Human prompt**

> Add lane geometry, but do not rebuild the PL bitstream.

**Selected model output**

Fit each lane in normalized coordinates, construct a lightweight BEV view,
estimate centre offset and curvature, and use hysteresis for departure. Map the
departure alarm onto the existing shared short-alarm bit.

**Decision and correction**

Accepted. The feature was implemented in PS only. The initial guided test tool
wrongly assumed a SOLID card; evidence showed the current card was DASHED. The
tool was changed to accept an explicit target or `AUTO`, and failed runs now
save diagnostic OSD, BEV and status JSON.

**Verification**

The automated suite covers geometry and shifted-lane departure. Final board
evidence requires centred, departure, alarm-output and cleared states.

## Case 5: static small-environment obstacles

**Human prompt**

> Static photos cannot support frame differencing. Treat this as small-scene
> object detection and draw boxes around a wall or other object.

**Selected model output**

Use a stationary empty-scene background model, phase-correlation alignment,
area/shape gates, temporal confirmation and short tracking IDs. Do not claim
vehicle-scale distance estimation.

**Decision and correction**

Accepted. A post-detection test that accidentally left a hand in the frame was
rejected as evidence. The clean test requires hands to leave after object
placement and also requires all boxes to disappear after removal.

**Verification**

The status contract covers `present`, `near`, `track_ids` and
`alarm_reason=3`. Final evidence is accepted only when the object is visible
without hands and the cleared state is separately recorded.

## Case 6: duplicate test discovery

**Human prompt**

> Run the final regression on the board.

**Observed output**

`pytest` stopped with `import file mismatch` because obsolete test copies were
still present in the board project root.

**Selected model output and correction**

Do not change product code. Run the declared suite with explicit `tests/`
paths, document the exact command, and add removal of obsolete root copies to
repository cleanup.

**Verification**

The explicit suite runs `45 passed` on the PYNQ board. The command and expected
count are part of the final checklist.

## Case 7: evidence audit

**Human prompt**

> Do not assume the report is current. Check claims against files.

**Selected model output**

Flagged three conflicts: the report still said 34 tests rather than 39, the
reported lane FPS predated lane geometry, and the obstacle screenshot contained
a hand. It also found no reusable `skill/` directory and no collaboration
record.

**Decision**

The report and PDF will be regenerated only after the final measurements.
Contradictory values are marked as pre-geometry or removed. The new Skill
directory and this record address the two missing scoring categories.
