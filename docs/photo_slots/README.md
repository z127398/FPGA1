# Photo Slots

The technical report already reserves five figure positions. To fill them,
place the real photographs in this directory with these exact names:

| File | Required content |
|---|---|
| `01_project_overview.jpg` | Board, OV5640, LCD, power and cables, LCD showing lane OSD |
| `02_board_front.jpg` | Front view showing main board interfaces and camera |
| `03_board_top.jpg` | Top view showing SoC, power, camera and expansion interfaces |
| `04_working_scene.jpg` | Printed test card, camera and LCD in the same frame |
| `05_board_detail.jpg` | Camera mount, keys, LEDs and buzzer detail |

Requirements:

- JPG or PNG; each image must be below 10 MB.
- The overview section accepts one image; the board section accepts up to four.
- Prefer 4:3 or 16:9 landscape photos with at least 2000 px on the long edge.
- Keep the LCD readable and avoid glare or reflections.
- Do not use LCD screenshots as substitutes for physical hardware photos.

After adding the photos, regenerate the report:

```bash
py -3 stage4/tools/render_report_pdf.py \
  --output docs/report/adas_report_final.pdf
```

The remaining seven technical-document figures are OV5640 runtime captures of
the printed red/green/yellow lights, solid/dashed lanes, lane departure and
obstacle detection. They are regenerated under `docs/evidence/`; no previous
photo is reused.
