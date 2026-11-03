# Stability and Safety Evidence

## Colour path

`video_probe.json` records the board result:

- colour frame channel means `(125.94, 134.44, 125.24)`;
- grey frame channel means `(130.42, 130.42, 130.42)`;
- selector values `0 → 1 → 0`;
- colour and grey probes both PASS.

The physical LCD was checked with labelled blue/green/red/white bars. The final
BGR framebuffer setting was confirmed by the operator after red and blue had
initially been exchanged.

Reference pattern: `color_bars.png`.

## Frame-driven watchdog

`watchdog_smoke.json` records an OSD processing stall injected 3 seconds into a
10-second run for 1.5 seconds:

```text
0.05 s  wd_timeout=0
3.53 s  wd_timeout=1  beep=1
4.54 s  wd_timeout=0
```

The LCD stopped receiving processed frames, while LED/buzzer hardware entered
the PL safe state. The next successful frame cleared the watchdog and the board
returned to normal operation.

## Strict three-mode smoke test

`modes_smoke.json` records 20 seconds per mode:

```text
traffic_light  20.65 FPS  wd_timeout=0
lane           37.48 FPS  wd_timeout=0
obstacle       25.16 FPS  wd_timeout=0
```

All three runs had no Python runtime error and the board restored Stage 2.

## Circular traffic-light gate

The final detector requires circularity >= 0.50, convexity >= 0.60 and ellipse
inertia ratio >= 0.40. Filled rectangles and narrow light strips are rejected
in unit tests. On the BSTLD held-out set, NONE false positives dropped from
10/10 to 0/10; overall circular-light accuracy is 31/40. Arrow signals are
outside the supported scope.
