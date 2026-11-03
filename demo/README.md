# Demo Video

Target: 3-minute 1080p clip, photo and LCD in the same frame.

Suggested sequence:

1. Show `video_probe()` PASS and the blue/green/red/white LCD bars.
2. PL passthrough with a stable mounted printed scene.
3. Traffic-light mode with circular red/green/yellow cards only.
4. Lane mode with PL grayscale input; solid lane alarms and dashed lane turns normally.
5. Clear the table, start obstacle mode, wait for background learning and
   the 10-second placement countdown, then place a bottle/box in the near zone.
6. Start watchdog monitoring, then run OSD with `stall_after=4.0` and
   `stall_duration=1.5`; show the LCD freeze, PL alarm and `wd=0→1→0` timeline.
7. Image injection fallback.

Keep raw clips in `demo/raw/` (excluded from Git by size) and the final cut in
`demo/`. Put the final video in a GitHub Release or an external link; do not
commit large video blobs directly.
