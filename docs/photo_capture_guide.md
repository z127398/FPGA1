# Stage 4 Photo Capture Guide

## Quick phone test (no printing)

Display the images in `stage4/assets/cards/` on a phone at high brightness:

- `red.png`, `green.png`, `yellow.png`
- `lane_solid.png`, `lane_dashed.png`

Hold the phone 30–40 cm from the OV5640, avoid reflections, and keep the image
perpendicular to the lens.

## Printed version

Use `stage4/assets/print/` (A4 300 dpi, 2480×3508):

- A4 **matte** paper, not glossy photo paper;
- image covers about 90% of the page, 5% margin;
- keep the label outside the photographed area;
- fix the sheet with clips or against a wall; do not hand-hold;
- use diffuse indoor light and avoid a bright ceiling reflection.

## Camera setup

- Distance 30–40 cm; the photo fills the frame with about 5% margin.
- Lens perpendicular to the paper; tilt causes perspective distortion and
  corrupts Hough slopes.
- Point at a white sheet for 3–5 s first so AWB converges.
- The first 1–2 frames after a photo switch are unstable; the code uses
  `skip=2`.
- Traffic-light circle should be at least 25 px in the 320×240 processing
  frame. If it is smaller, crop/zoom and reprint.

## Acceptance sequence

Start with `run_traffic_light()` for light cards and `run_lane()` for lane
cards. The modes are mutually exclusive. The light detector accepts circular
lamps only; arrow lamps are intentionally rejected.

1. `red.png`: all LEDs off + short beep.
2. `green.png`: LED1 on.
3. KEY0 cycles LED0/1/2.
4. `lane_solid.png` + KEY0: three LEDs blink + continuous beep.
5. `lane_dashed.png` + KEY0: normal turn indicator.
6. `red.png` + KEY1: continuous alarm.
7. Inject a 1.5 s OSD processing stall: watchdog LEDs alternate + 1 Hz beep,
   then recover automatically.
8. `read_image_demo()`: LCD image fallback.

## Static environment sequence

Start with `start_obstacle()`, a fixed camera and an empty desk.
Wait for the 24-frame median background to finish (`LEARNING BACKGROUND`
disappears), then place a bottle, box and cup one at a time. New static
objects appear as `OBJECT`; only objects in the lower-centre near zone display
`NEAR` and set `obstacle=1`. Remove the objects and wait about 10 frames for
the boxes to clear. If the scene was not empty at startup or the camera moved
substantially, empty the desk and call `relearn_background()`.

## Recording

Record a 3-minute 1080p clip with the photo and LCD in the same frame.
Keep raw clips in `D:\adas_pl\demo\raw\` and the final cut in `D:\adas_pl\demo\`.

## Submission photo slots

The report reserves these exact filenames under `docs/photo_slots/`:

- `01_project_overview.jpg`
- `02_board_front.jpg`
- `03_board_top.jpg`
- `04_working_scene.jpg`
- `05_board_detail.jpg`

Add the physical photographs using these names, then regenerate
`docs/report/adas_report_final.pdf`. The overview accepts one image; up to four
board detail images may be uploaded separately.
