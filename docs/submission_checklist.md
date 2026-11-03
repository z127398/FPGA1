# Submission Checklist

## Engineering (freeze target 10/27)

- [x] Stage 3 bitstream uploaded and verified
- [x] Stage 4 realtime pipeline, heartbeat, FSM, watchdog
- [x] Traffic light 20/20 red, 20/20 green, 20/20 yellow
- [x] Solid/dashed lane capture
- [x] Small-environment static obstacle mode
- [x] Colour/grey PL selector probe and LCD R/B correction
- [x] Frame-driven heartbeat and injected-stall watchdog recovery
- [x] Strict traffic-light, lane and obstacle modes
- [x] Circular traffic-light shape gate (arrows unsupported)
- [x] 45/45 automated tests
- [x] FPS/latency evidence
- [x] PL grayscale lane preprocessing with measured A/B result
- [x] BSTLD 100-case local benchmark (partial mirror; limitations disclosed)
- [x] TuSimple 20-frame manual lane evaluation
- [ ] 3-minute 1080p raw video

## Documentation and submission (10/27–10/31)

- [x] README.md
- [x] docs/report/adas_report.md
- [x] docs/report/adas_technical_document.docx
- [x] docs/report/adas_technical_document.pdf
- [x] docs/stage4_debug.md
- [x] docs/stage4_acceptance.md
- [x] docs/photo_capture_guide.md
- [x] evidence index and demo shot list
- [x] Four standalone mode notebooks

## Git/GitHub

- [x] Create public repository: `https://github.com/z127398/FPGA1`
- [x] Review staged files
- [x] Push source submission at commit `383a27c`
- [x] Push repository-structure documentation at commit `492ce38`
- [x] Add the corrected technical document and push commit `d44873a`
- [ ] Create `stage4-freeze` tag
- [ ] Create a Release or external link for the 3-minute video

Current state: the source repository and corrected 21-page technical document
are online. The freeze tag and video Release/link are pending.
