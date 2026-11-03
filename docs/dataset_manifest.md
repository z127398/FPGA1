# Dataset Manifests and Evaluation

The runtime does not download datasets or invent accuracy numbers. Raw data and
generated crops stay under the ignored `datasets/` directory; only manifests
and result JSON files are tracked.

## BSTLD subset

The local mirror is partial:

- 105 labelled training frames mapped successfully;
- 114 test frames with no active-light boxes;
- one source frame contains an active yellow box.

Generate the reproducible 100-case benchmark:

```powershell
$env:PYTHONPATH='D:\adas_pl\stage4'
py -3 D:\adas_pl\stage4\tools\build_bstld_crops.py
```

The script creates 25 RED, GREEN, YELLOW and NONE cases, split 15/10 per class
into tuning and held-out manifests. Red and green use distinct real source
images. Yellow uses the one real source plus 24 deterministic brightness/blur
variants, marked as `origin=augmented`; it must not be described as independent
real-image accuracy.

Crop policy:

- target crop with 35% padding on each side;
- other labelled lights are masked;
- minimum side is upscaled to 96 px;
- NONE frames are resized to the runtime 320×240 input;
- each CSV row records source ID, crop box, condition and image SHA-256.

Evaluate:

```powershell
$env:PYTHONPATH='D:\adas_pl\stage4'
py -3 D:\adas_pl\stage4\tools\eval_manifest.py tl `
  D:\adas_pl\docs\report\metrics\manifest_bstld_test.csv `
  --root D:\adas_pl\datasets\bstld_crops `
  --json-out D:\adas_pl\docs\report\metrics\bstld_test_results.json
```

Final results:

| Split | Correct | Accuracy | Note |
|---|---:|---:|---|
| tuning, 60 cases | 46 | 76.7% | includes yellow variants |
| held out, 40 cases | 31 | 77.5% | circular-shape filter enabled |
| held out, active lights only | 21/30 | 70.0% | RED 4/10, GREEN 7/10, YELLOW 10/10 |
| held out, NONE only | 10/10 | 100% | bright signs rejected by shape |

The detector intentionally accepts circular lamps only. Non-circular arrows
and elongated reflections are rejected; the lower active-light recall is the
documented cost of reducing false positives.

## TuSimple lane subset

TuSimple's official annotations contain lane geometry but no SOLID/DASHED
material labels. Twenty frames are selected with visible boundaries on both
sides of the image centre, split 10 tuning / 10 held out, and manually labelled
left/right. The held-out set contains five solid-edge scenes and five
all-dashed scenes.

The exact 20 selected candidate IDs can be regenerated with:

```powershell
$env:PYTHONPATH='D:\adas_pl\stage4'
py -3 D:\adas_pl\stage4\tools\prepare_tusimple_subset.py `
  --indices 3,6,9,10,14,0,1,4,5,7,18,22,26,30,31,11,13,15,20,35
```

Evaluation uses the runtime resolution:

```powershell
$env:PYTHONPATH='D:\adas_pl\stage4'
py -3 D:\adas_pl\stage4\tools\eval_manifest.py lane `
  D:\adas_pl\docs\report\metrics\manifest_tusimple_test.csv `
  --root D:\adas_pl\datasets --size 320x240 `
  --json-out D:\adas_pl\docs\report\metrics\tusimple_test_results.json
```

Final results:

| Split | Correct side labels | Accuracy |
|---|---:|---:|
| tuning, 10 frames | 15/20 | 75.0% |
| held out, 10 frames | 16/20 | 80.0% |
| held-out right SOLID | 5/5 | 100% |
| held-out DASHED sides | 11/15 | 73.3% |

The 5-frame detector vote is not counted as an accuracy gain in these
single-frame measurements.

## Card smoke manifests

`stage4/assets/manifest_cards_tl.csv` and
`stage4/assets/manifest_cards_lane.csv` verify the generated phone/print cards:

```bash
PYTHONPATH=. python3 tools/eval_manifest.py tl assets/manifest_cards_tl.csv --root assets
PYTHONPATH=. python3 tools/eval_manifest.py lane assets/manifest_cards_lane.csv --root assets
```

These are controlled-condition smoke tests, not dataset generalization.
