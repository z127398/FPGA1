# PYNQ Safe Frame Pipeline

## Problem

A PYNQ video application can look healthy while its PS loop is stalled. If the
PL alarm state depends on a periodic CPU timer, Linux scheduling or a dead
Python thread can leave the actuator in an unsafe state.

## Pattern

1. Define one fixed-width PL control word and one PL status word.
2. Feed the heartbeat only after a frame has been read, processed, composed
   and written back successfully.
3. Advance heartbeat on successful frame completion, not from `sleep()` or a
   background timer.
4. Implement a PL timeout that enters a safe output state without PS help.
5. Clear the timeout only after PS resumes and sends a valid frame heartbeat.
6. On every exception or interrupt, restore a known quiet bitstream and write
   neutral control values.

Example control contract from the reference project:

```text
t = traffic_light | lane_left << 2 | lane_right << 4
    | obstacle << 6 | force_ps << 7 | turn_ps << 8 | heartbeat << 10
```

## Failure conditions

- Heartbeat is toggled before the frame is written back: the watchdog can be
  fed while the visible pipeline is frozen.
- GPIO writes omit the write mask: some PYNQ releases accept the call but write
  no bits.
- A previous overlay remains loaded after an interrupted test: the next run can
  observe stale registers.
- The control word and PL RTL drift: software may report safety while hardware
  receives different fields.

## Verification

- Inject a processing stall longer than the watchdog interval.
- Confirm `wd_timeout=0 -> 1` while PS is stalled.
- Resume processing and confirm `wd_timeout -> 0`.
- Restore the quiet bitstream and verify no alarm output remains active.

## Portability

This pattern applies to camera pipelines, industrial inspection, robotics
telemetry and any design where a PS monitor cannot be trusted during a hang.
