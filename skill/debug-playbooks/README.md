# Debug Playbooks

## GPIO command appears to run but no bits change

- Symptom: heartbeat or mode bits stay unchanged after `channel1.write()`.
- Likely cause: PYNQ 2.7 requires `channel1.write(value, 0xFFFF)`; the write
  mask is the second argument.
- Verify: write one known bit pattern, read the register back with the required
  mask, then exercise LED or buzzer output.

## Video is present but the wrong object type is bound

- Symptom: `layer.video_in` is missing after adding a hierarchy.
- Likely cause: PYNQ auto-binds a hierarchy as generic `DocumentedHierarchy`
  rather than `VideoIn`.
- Verify: inspect the HWH hierarchy path, instantiate the intended frontend
  class explicitly, and test one complete frame.

## Red and blue are swapped

- Symptom: detector results are correct while LCD colours are reversed.
- Likely cause: OpenCV BGR frame written into a display frontend expecting a
  different channel order.
- Verify with colour bars and sample channel means before changing perception.

## Duplicate pytest collection error

- Symptom: `import file mismatch` for tests with the same basename.
- Likely cause: stale test copies remain in the repository root.
- Verify: run the declared suite path explicitly or remove obsolete copies
  after preserving them in a backup.

## FPS drops after adding visualization

- Symptom: detection still works but frame rate falls sharply.
- Likely cause: full-resolution warps, OSD composition or display writes are
  being performed more often than necessary.
- Verify: record `read_ms`, `process_ms`, `osd_ms` and `write_ms` separately
  before changing thresholds or reducing resolution.
