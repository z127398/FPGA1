# 3-Minute Demo Shot List

Record 1080p with the photo/card and LCD in the same frame. Use a tripod or
fixed support; the environment obstacle segment requires a stationary camera.

| Time | Shot | Expected result |
|---|---|---|
| 0:00–0:15 | Hardware + architecture title | OV5640, board, LCD |
| 0:15–0:30 | LCD colour bars + colour/grey probe | blue/green/red/white correct |
| 0:30–0:50 | Passthrough color → new frame stability | live video, PL bypass |
| 0:50–1:15 | Traffic-light mode: red → green → yellow circular cards | frame only on round lamps; stop/beep/LED1 |
| 1:15–1:35 | Lane mode: solid/dashed + KEY0/KEY1 | SOLID alarm, DASHED normal turn |
| 1:35–1:55 | Obstacle mode: empty table → learning → bottle/box | OBJECT NEAR + short beep |
| 1:55–2:35 | Frame-driven heartbeat; inject 1.5 s PS stall | LCD freezes, PL alarm, `wd=0→1→0` |
| 2:35–2:55 | Metrics and evidence | controlled/dataset results separated |
| 2:55–3:00 | Image injection fallback | demo never stops |

Keep raw clips in `demo/raw/`; final video goes in `demo/` or a GitHub Release.
