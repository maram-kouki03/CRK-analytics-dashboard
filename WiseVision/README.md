# WiseVision — Boutique CCTV Analytics

Turn a fixed shop camera into two numbers, automatically:

| Output | Meaning |
|---|---|
| **Clients entered** | customers who walked *into* the shop through the door |
| **Interactions (PEC)** | customers who were actually served by a staff member |

The production solution is **[`Final-code_v1.py`](Final-code_v1.py)** — one standalone file,
no imports from any other project file. Everything below documents that file.

Measured on real single-camera boutique footage (1920×1080 @ 25 fps):
**87 % accuracy on entry counting, 90 % on interaction counting** vs. hand-labelled ground truth.

---

## 1. Quick start

```bash
# from the repo root
python -m venv venv
venv\Scripts\activate                 # Windows;  source venv/bin/activate on Linux

# PyTorch FIRST, with CUDA (much faster; CPU also works, code auto-falls back)
pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu118

pip install -r requirements.txt
```

Then open `Final-code_v1.py` and set the two paths at the top:

```python
SOURCE_VIDEO_PATH = "testvid_playable.mp4"   # your input video
TARGET_VIDEO_PATH = "SC_output23.mp4"        # annotated output video
```

```bash
python Final-code_v1.py
```

Model weights **download themselves on first run** — nothing to fetch by hand:

- `yolo11m-pose.pt` — person boxes + 17 body keypoints (via ultralytics)
- `osnet_ain_x1_0_msmt17.pt` — OSNet ReID for BoT-SORT (via boxmot)

> **A new camera needs its zones re-drawn before the numbers mean anything.**
> Jump to [§7 Onboarding a new camera](#7-onboarding-a-new-camera).

---

## 2. Pipeline overview

One pass over the video. Every `SKIP`-th frame is *processed*; the frames in between are
just re-drawn with the previous labels and written out, so the output video stays smooth
at full frame rate.

```
                     ┌──────────────────────────────────────────┐
   video frame  ───► │ 1. YOLO11m-pose                          │
                     │    person boxes + 17 keypoints each      │
                     └────────────────────┬─────────────────────┘
                                          ▼
                     ┌──────────────────────────────────────────┐
                     │ 2. MIRROR_ZONES filter                   │
                     │    drop reflections (feet-in-polygon)    │
                     └────────────────────┬─────────────────────┘
                                          ▼
                     ┌──────────────────────────────────────────┐
                     │ 3. BoT-SORT + OSNet ReID                 │
                     │    → a stable track id per person        │
                     │    (ids only; role is NOT from ReID)     │
                     └────────────────────┬─────────────────────┘
                                          ▼
                     ┌──────────────────────────────────────────┐
                     │ 4. ROLE: SELLER or CLIENT                │
                     │    beige trousers AND white shirt,       │
                     │    read at the body keypoints            │
                     │    + SELLER_ZONES override               │
                     └────────────────────┬─────────────────────┘
                                          ▼
                     ┌──────────────────────────────────────────┐
                     │ 5. IGNORE_ZONES filter (CLIENTS only)     │
                     │    drop static false detections          │
                     └───────┬──────────────────┬───────────────┘
                             ▼                  ▼
              ┌──────────────────────┐  ┌───────────────────────────┐
              │ 6. ENTRY COUNT       │  │ 7. INTERACTION (PEC)      │
              │  ordered 2-zone pass │  │  proximity + dwell time,  │
              │  + staff revert      │  │  counted once per client  │
              └──────────┬───────────┘  └───────────┬───────────────┘
                         └──────────┬───────────────┘
                                    ▼
                     ┌──────────────────────────────────────────┐
                     │ 8. Draw overlay → write output video     │
                     │    + print the final report              │
                     └──────────────────────────────────────────┘
```

Two design rules run through the whole file:

1. **Roles are decided fresh every processed frame** from pixels — no memory, no vote-locking.
   A track that is briefly misread self-corrects on the next frame.
2. **Track ids are used only where identity genuinely matters** — de-duplicating an
   interaction, and reverting a miscounted entry. Entry counting itself is
   *id-free* on purpose (see §5), because ids are exactly what break under occlusion at a doorway.

---

## 3. Step 4 in detail — SELLER vs CLIENT

The staff uniform is **beige trousers + white shirt**. Instead of averaging colour over a
whole box (which mixes in background, skin and shopping bags), Final-code_v1 reads colour **at the
body keypoints** that YOLO-pose gives us — the pixels that are guaranteed to be *on the
person's clothes*.

```
        COCO keypoints used
                                        WHITE SHIRT check
       5 ●───────────● 6          ←     shoulders  (UPPER_KP_IDX = [5, 6])
         │           │                  need WHITE_KP_MIN = 1 of 2 white
         │           │
      11 ●───────────● 12         ←┐
         │           │             │    BEIGE TROUSERS check
         │           │             │    hips + knees (LOWER_KP_IDX = [11,12,13,14])
      13 ●           ● 14         ←┘    need BEIGE_KP_MIN = 1 of 4 beige
         │           │
         ○           ○                  ankles 15,16 — DELIBERATELY SKIPPED
                                        (they sit on shoes / floor, not trousers)
```

For each keypoint above `KP_CONF` confidence, take a **7×7 px patch** (`KP_PATCH_R = 3`)
centred on it and test the patch:

- **beige** → ≥ `KP_PATCH_FRAC` (50 %) of its pixels fall inside the HSV band
  `UNIFORM_BAND_LO..HI` = `[18,0,51]..[49,54,240]`
- **white** → ≥ `WHITE_PATCH_FRAC` (50 %) of its pixels have low saturation
  (`S ≤ WHITE_S_MAX`) and high brightness (`V ≥ WHITE_V_MIN`)

A patch instead of a single pixel absorbs keypoint jitter; the band's saturation ceiling
is what rejects bare skin (skin is beige-*hued* but far more saturated).

**The rule:**

```
SELLER  ⟺  (≥1 of 4 leg keypoints beige)  AND  (≥1 of 2 shoulders white)
```

Trousers are tested first — if they are not beige the person is a CLIENT immediately and
the white check never runs. Low-confidence (occluded) keypoints are skipped rather than
guessed.

**The SELLER_ZONES override.** A staff member seated behind the counter has no visible
legs, so the trouser cue can never fire. If ≥ `SELLER_ZONE_FRAC` (50 %) of their box
overlaps a staff-area polygon **and** the white-shirt check passes, they are forced to
SELLER. The white gate is what stops a customer leaning on the counter from being
promoted to staff.

Everyone who is not a SELLER is a CLIENT. Clients are never given a visible id.

> **Why not ReID / a photo of the staff?** It was tried, in an earlier method kept locally
> (BoT-SORT + a reference-photo gallery). At this camera's resolution and distance, OSNet
> embeddings of a white-top customer land as close to the staff gallery as the staff
> themselves. Colour-at-keypoints is cruder but it is *decidable per frame* and does not
> drift. A learned alternative was also trained — see §14.

---

## 4. Step 5 — the two false-detection filters

YOLO is not wrong here; the *scene* is. Two polygon filters clean it up:

| Filter | Applies to | Test | Purpose |
|---|---|---|---|
| `MIRROR_ZONES` | **everyone**, before tracking | feet (bottom-centre) inside polygon | a reflection is never a real person, so it must never even become a track |
| `IGNORE_ZONES` | **clients only**, after the role decision | > `IGNORE_ZONE_FRAC` of the box overlaps | kills static objects YOLO reads as people (a handbag on a shelf). Client-only, so a real staff member standing there is kept |

The ordering matters: mirrors are dropped **before** BoT-SORT so reflections never get an
id at all, while ignore zones run **after** the role is known so they can spare sellers.

---

## 5. Step 6 — entry counting (ordered two-zone pass)

The obvious approach — a line with a signed-distance test — was replaced. It failed twice
over: a customer's box centre jitters across the line (double counts), and a customer
occluded in the doorway loses their track id (missed counts).

Final-code_v1 instead draws **two adjacent polygons across the doorway** and reads the **order** in
which a person visits them. Direction comes out of the order; there is no line and no
geometry math at all.

```
      outside                                  inside the shop
            ┌───────────┬───────────┐
            │  ZONE 1   │  ZONE 2   │
            │  (door)   │  (shop)   │
            └───────────┴───────────┘
              1  ──────────►  2         =  ENTERING   → +1
              2  ◄──────────  1         =  leaving    → not counted
              only one zone touched     =  loitering  → not counted
```

"In a zone" = ≥ `ENTER_ZONE_FRAC` (10 %) of the person's **box** overlaps it, sampled on a
6×6 grid.

**The id-free part.** Rather than trusting BoT-SORT at the door, entry tracking keeps its
own tiny table of `[cx, cy, last_zone, counted, last_frame]` and links a detection to the
nearest recent entry within `ZONE_MATCH_DIST` (200 px), expiring after `ZONE_TTL`
(10 processed frames). **A customer with no track id at all is still counted correctly** —
this is the single biggest reason the entry number is reliable.

**The staff revert.** A real staff member who walks near the door can be misread as a
CLIENT for a moment and counted +1. So when a counted track *does* have an id, that id is
remembered for `ENTRY_REVERT_SECS`. If it accumulates `REVERT_MIN_SELLER_SECS` of SELLER
time inside that window, the +1 is undone.

The evidence is **cumulative, not consecutive** — 0.4 s + 0.3 s + 0.4 s spread across
flicker still adds up to 1 s and cancels the count. That was the fix that made the revert
actually fire; requiring an unbroken run almost never triggered.

Console line when it happens:

```
[CNT] f412 REVERT -1 (tid 7 seller 0.6s cumulative, 1.4s after entry) -> count=5
```

---

## 6. Step 7 — interaction counting (PEC)

"Was this customer actually served?" is modelled as **proximity sustained over time**.

Each person gets a circle of radius `INTERACTION_RADIUS` (200 px) at their box centre. A
customer is *in contact* when their circle overlaps **any** staff member's circle by at
least `INTERACTION_OVERLAP_MIN` (35 %) of a circle's area. Equal radii, so the overlap
fraction is a clean stand-in for distance:

| centre distance | overlap |
|---|---|
| 0 px | 1.00 (concentric) |
| 162 px | ≈ 0.50 |
| 200 px | ≈ 0.39 |
| ≥ 400 px | 0.00 |

The test is **omnidirectional** — near *any* seller, from any side, counts.

Contact time then accumulates, and is **grace-tolerant**: a no-contact gap up to
`INTERACTION_GRACE_SECS` (2 s) does **not** reset the timer. The customer turning away,
being briefly occluded, or the detector dropping a frame all preserve the accumulated
seconds. Only a longer gap resets to zero.

Once accumulated contact reaches `INTERACTION_MIN_SECS` (5 s) it counts as **one**
interaction. The customer's track id is then remembered forever, so:

- the same customer is **never counted twice** (the id is checked before every count), and
- a yellow `+1` is drawn on their box for the rest of their visit.

The result is a single shop-wide interaction total.

---

## 7. Onboarding a new camera

**All zone coordinates in Final-code_v1.py are specific to one camera at one 1920×1080 view.**
Move the camera and every number becomes meaningless. Re-draw them:

```bash
python "tools for help/pick_zones.py" testvid_playable.mp4        # frame 0
python "tools for help/pick_zones.py" testvid_playable.mp4 4080   # a specific frame
```

Controls: **left-click** add corner · **n** finish this polygon and start the next ·
**u** undo · **s** print all polygons · **q/ESC** quit (also prints). Copy the printed
lists straight into the matching constant in Final-code_v1.py.

Draw them in this order:

| # | Constant | What to draw | Watch out for |
|---|---|---|---|
| 1 | `ENTER_ZONE_1` | the doorway strip crossed **first** when entering (outside) | the two strips must touch, not overlap |
| 2 | `ENTER_ZONE_2` | the strip reached **second** when entering (interior) | getting 1 and 2 backwards counts exits as entries |
| 3 | `SELLER_ZONES` | where staff **bodies** are (behind the counter) | cover the body, not just floor — the test is box overlap |
| 4 | `MIRROR_ZONES` | mirrors and reflective glass | keep generous; a reflection costs more than a miss |
| 5 | `IGNORE_ZONES` | shelves/objects YOLO reads as people | keep **tight** — these silently delete real customers |

Then re-check the uniform band. If the new footage has different lighting or a different
uniform, the baked band `[18,0,51]..[49,54,240]` will be wrong. See §9 for how to
re-learn it.

Finally, sanity-run with `MAX_FRAMES = 300` and `DEBUG_ZONE = True` before committing to a
full pass.

---

## 8. Configuration reference

Every knob is a constant at the top of Final-code_v1.py. Marked ⭐ = you will probably touch it.

### Input / output / models

| Constant | Value | Meaning |
|---|---|---|
| `SOURCE_VIDEO_PATH` | `testvid_playable.mp4` | ⭐ input video |
| `TARGET_VIDEO_PATH` | `SC_output23.mp4` | ⭐ annotated output |
| `MODEL_NAME` | `yolo11m-pose.pt` | detector + keypoints. **Must be a `-pose` model** — the whole role logic needs keypoints |
| `REID_MODEL` | `osnet_ain_x1_0_msmt17.pt` | ReID model for BoT-SORT |
| `DEVICE` / `HALF_PRECISION` | auto | CUDA + FP16 if a GPU is present, else CPU |

### Detection

| Constant | Value | Meaning |
|---|---|---|
| `DETECT_CONF` | `0.07` | intentionally very low — keep *every* person, then classify. Filtering happens by role and zone, not by confidence |
| `SKIP` | `2` | ⭐ process every 2nd frame. `1` = steadiest, ~2× slower. Raise for speed |
| `PERSON_CLASS_ID` | `0` | COCO "person" |

### BoT-SORT / ReID

| Constant | Value | Why this value |
|---|---|---|
| `TRACK_BUFFER` | `180` | frames a lost track survives — long, so a customer occluded behind a shelf keeps their id |
| `CMC_METHOD` | `"sof"` | sparse optical flow. ECC was tried and spammed *"did not converge"* on this fixed camera |
| `APPEARANCE_EMA_ALPHA` | `0.95` | patched into BoT-SORT at runtime so one bad crop barely moves a track's appearance template |
| `APPEARANCE_THRESH` | `0.3` | ReID match threshold |
| `PROXIMITY_THRESH` / `MATCH_THRESH` | `0.8` / `0.8` | IoU gating |
| `TRACK_HIGH/LOW_THRESH`, `NEW_TRACK_THRESH` | `0.4` / `0.1` / `0.2` | association tiers |

### The uniform cue ⭐

| Constant | Value | Meaning |
|---|---|---|
| `UNIFORM_BAND_LO` / `HI` | `[18,0,51]` / `[49,54,240]` | ⭐ the HSV beige band. `H` tan/khaki, `S ≤ 54` (dull — rejects skin), `V 51..240` (anything but deep shadow) |
| `LOWER_KP_IDX` | `[11,12,13,14]` | hips + knees |
| `BEIGE_KP_MIN` | `1` | ⭐ beige leg keypoints required (of 4) |
| `UPPER_KP_IDX` | `[5,6]` | shoulders |
| `WHITE_KP_MIN` | `1` | ⭐ white shoulders required (of 2) |
| `KP_CONF` | `0.07` | minimum keypoint confidence to test it |
| `KP_PATCH_R` | `3` | half-window → a 7×7 px patch |
| `KP_PATCH_FRAC` / `WHITE_PATCH_FRAC` | `0.5` / `0.5` | fraction of a patch that must match |
| `WHITE_S_MAX` / `WHITE_V_MIN` | `80` / `110` | ⭐ what counts as "white" |

### Zones ⭐

| Constant | Value | Meaning |
|---|---|---|
| `ENTER_ZONE_1` / `ENTER_ZONE_2` | polygons | ⭐ doorway strips, **in entering order** |
| `ENTER_ZONE_FRAC` | `0.10` | box overlap to be "in" an entry zone |
| `ZONE_MATCH_DIST` / `ZONE_TTL` | `200` px / `10` frames | id-free re-association at the door |
| `SELLER_ZONES` / `SELLER_ZONE_FRAC` | polygons / `0.50` | ⭐ staff area override |
| `MIRROR_ZONES` | polygons | ⭐ reflections (feet-in-polygon) |
| `IGNORE_ZONES` / `IGNORE_ZONE_FRAC` | polygons / `0.1` | ⭐ static false detections (clients only) |

### Counting logic ⭐

| Constant | Value | Meaning |
|---|---|---|
| `ENTRY_REVERT_SECS` | `2.9` | window after an entry in which a staff flip can cancel it |
| `REVERT_MIN_SELLER_SECS` | `0.5` | **cumulative** seller seconds needed inside that window |
| `INTERACTION_RADIUS` | `200` px | circle at each person's box centre |
| `INTERACTION_OVERLAP_MIN` | `0.35` | ⭐ circle overlap = "in contact" |
| `INTERACTION_MIN_SECS` | `5` | ⭐ accumulated contact before it counts |
| `INTERACTION_GRACE_SECS` | `2` | no-contact gap that does *not* reset the timer |

### Debug

| Constant | Value | Meaning |
|---|---|---|
| `DEBUG_CALIB` | `True` | print per-track stats at the end |
| `DEBUG_ZONE` | `True` | overlay `Z=…% W=…%` on every box — **turn off for delivery** |
| `MAX_FRAMES` | `0` | `>0` stops early. Set to ~300 for a quick test |

### ⚠️ Dead constants — do not tune these

Final-code_v1 evolved from earlier iterations (SC1/SC2, kept locally, not published here)
and some of that machinery is still in the file but **never runs**.
The `UniformModel` class is defined and never instantiated; these constants are read only
by it or by its helpers:

```
USE_REF_COLORS   SELLER_REF_DIR   COLOR_TAKE     WHITE_MIN      SELLER_VOTES
SEED_SECONDS     SEED_BEIGE_MIN   COLOR_PCT_LO   COLOR_PCT_HI   COLOR_MARGIN
BEIGE_H_MIN/MAX  BEIGE_S_MAX      BEIGE_V_MIN
```

Likewise the functions `is_uniform()`, `torso_white_ratio()`, `beige_pants_ratio()` and
`lower_body_hsv()` are unreachable at runtime. `body_white_ratio()` survives only to draw
the `W=` debug number.

Two things this means in practice: the **module docstring at the top of Final-code_v1.py is stale**
(it still describes the SEED window and `SELLER_VOTES` vote-locking, neither of which
the code does), and **changing any constant in the list above has zero effect**. The live rule
is the one in §3. This is kept rather than deleted because the band re-learning path (§9)
reuses `UniformModel`.

---

## 9. Re-learning the uniform band

The baked band was produced once from reference crops. To redo it for new footage or a new
uniform:

1. Put 10–20 tight crops of staff (legs visible) in a folder, e.g. `reference_image/`.
   `tools for help/split_montage.py` will cut a horizontal montage into individual PNGs.
2. In a scratch copy, call `UniformModel.learn_from_dir("reference_image")` and print
   `bounds()`. It keeps only roughly-beige pixels (the broad `BEIGE_*` pre-gate), takes the
   5th–95th percentile per channel, then pads by `COLOR_MARGIN`.
3. Copy the printed band into `UNIFORM_BAND_LO` / `UNIFORM_BAND_HI`.

The two-stage design is deliberate, not redundant: the **broad** gate (`H` 22–55) harvests
candidate pixels, the **tight** learned band (`H` 18–49) is the final answer.

At runtime the band is **baked into the source**, so production needs **no image folder at all**.

---

## 10. Reading the output

### Video overlay

| What you see | Meaning |
|---|---|
| **red box** `SELLER #id` | staff |
| **green box** `CLIENT #id` | customer |
| thin circle, red/green | that person's 200 px interaction circle |
| **thick yellow circle** | this customer is in contact with a seller *right now* |
| yellow **`+1`** at the bottom of a box | this customer has been counted as served |
| green dot on a hip/knee | that keypoint's patch **is** beige · red dot = is not |
| white dot on a shoulder | that keypoint's patch **is** white · blue dot = is not |
| yellow `Z=..% W=..%` in a box | `DEBUG_ZONE`: seller-zone overlap % and whole-box white % |
| yellow / blue polygons `1` `2` | entry zones, in entering order |
| red polygons | seller zones · **magenta** mirror zones · **grey** ignore zones |

The keypoint dots are the best debugging tool in the file: they show **exactly which pixels
the role decision read**. If a real seller shows red leg dots, the band is wrong for that
lighting — not the logic.

### Console

Live events:

```
[CNT] f250 ENTER (1->2) at (1653,852) -> count=3
[CNT] f412 REVERT -1 (tid 7 seller 0.6s cumulative, 1.4s after entry) -> count=2
[PEC] f900 INTERACTION +1 (client tid 14 at t=72.0s) -> total=5
```

Final report:

```
========== RESULT ==========
Processed frames : 1523
Clients entered  : 12
Interactions     : 5
Output video     : SC_output23.mp4
Full pipeline    : 46.3 ms/frame (21.6 FPS)
============================
```

With `DEBUG_CALIB` on, a per-track table also prints — `frames`, `seller_frames`,
`beige_frames` for the 20 longest-lived tracks. A track with high `beige_frames` but low
`seller_frames` means the trousers pass and the **shirt** check is what's failing.

---

## 11. Tuning cheat-sheet

| Symptom | Fix |
|---|---|
| a real seller is labelled CLIENT | check the keypoint dots first. Red legs → widen `UNIFORM_BAND` (raise `S` ceiling / lower `V` floor). Blue shoulders → raise `WHITE_S_MAX` or lower `WHITE_V_MIN` |
| a customer flips to SELLER | narrow the band's `S` ceiling (`54 → 40`); raise `BEIGE_KP_MIN` to `2`; raise `WHITE_KP_MIN` to `2` |
| a seated staffer stays CLIENT | extend `SELLER_ZONES` over their body; lower `SELLER_ZONE_FRAC` |
| entries counted twice | widen the two entry zones so a jittering box can't skip one; raise `ENTER_ZONE_FRAC` |
| entries missed | lower `ENTER_ZONE_FRAC`; make the strips deeper along the walking direction; raise `ZONE_TTL` |
| exits counted as entries | `ENTER_ZONE_1` and `ENTER_ZONE_2` are swapped |
| staff at the door inflate entries | raise `ENTRY_REVERT_SECS`; lower `REVERT_MIN_SELLER_SECS` |
| interactions over-counted (passers-by) | raise `INTERACTION_MIN_SECS`; raise `INTERACTION_OVERLAP_MIN` (tighter distance) |
| interactions missed | lower `INTERACTION_MIN_SECS`; raise `INTERACTION_GRACE_SECS`; enlarge `INTERACTION_RADIUS` |
| phantom people | reflections → `MIRROR_ZONES`; static objects → `IGNORE_ZONES` (keep tight) |
| too slow | raise `SKIP`; use `yolo11s-pose.pt`; confirm CUDA is actually being used (the banner prints the GPU) |

---

## 12. Helper tools (`tools for help/`)

| Script | What it does |
|---|---|
| **`pick_zones.py`** | ⭐ click polygons on a frame → prints ready-to-paste coordinate lists. **The tool you need for every new camera.** |
| `pick_line.py` | click two points → line coordinates. Legacy; Final-code_v1 uses zones, not lines |
| `video_info.py` | print a video's resolution / fps / frame count |
| `test-detection.py` | detection-only preview, no tracking or counting — use it to check the detector before debugging the logic |
| `clean_corrupt_frames.py` | rewrite a video with HEVC decode-error frames dropped. **Read this if a video misbehaves** — see the warning below |
| `concat_videos.py` | join clips with ffmpeg (finds ffmpeg on PATH or the imageio-ffmpeg bundle) |
| `split_montage.py` | cut a horizontal crop montage into individual PNGs (for building reference/uniform crops) |

> ### ⚠️ Corrupt-frame warning
> Some source footage (the `CRK*.mp4` files) has frames where the H.265 decoder lost its
> reference frame. They come out near-grey and flat with ghost macroblocks, and they
> **survive sequential decode** while poisoning everything downstream: phantom YOLO boxes,
> garbage ReID embeddings, inflated counts.
>
> Two consequences: **decode sequentially, never seek** on that footage, and run it through
> `clean_corrupt_frames.py` first, then point Final-code_v1 at the cleaned output. The detector
> (calibrated on all 65 k frames of `testvid_playable.mp4`) drops a frame only when it is
> *both* near-grey (`sat_mean < 2`) *and* flat (`gray_frac > 0.94`), so merely dim or
> merely low-texture frames are kept.

---

## 13. Repository layout

This repository is deliberately minimal — **four things, nothing else**:

```
.
├── Final-code_v1.py                 ⭐ THE PIPELINE — one standalone file
│                                       (documented by this README)
├── README.md                        ⭐ this file
├── requirements.txt                 ⭐ dependencies + install order
│
├── tools for help/                  ⭐ helper scripts — see §12
│   ├── pick_zones.py                   draw the zone polygons  ← needed for §7
│   ├── pick_line.py                    legacy line picker
│   ├── video_info.py                   print fps / size / frame count
│   ├── test-detection.py               detection-only preview
│   ├── clean_corrupt_frames.py         strip HEVC decode-error frames
│   ├── concat_videos.py                join clips with ffmpeg
│   └── split_montage.py                split a crop montage into PNGs
│
└── .gitignore
```

Two things are **not** in the repo and never should be:

- **Model weights (`*.pt`) and videos (`*.mp4`)** — git-ignored. The weights
  auto-download on first run; you supply your own video.
- **Earlier iterations and experiments** — the SC1/SC2/SC4 versions, the ResNet18
  classifier branch (§14), and the two superseded methods (BoT-SORT + reference-photo
  ReID, and a ByteTrack baseline). They live on the author's machine only. Everything
  needed to run and re-tune the pipeline is in the four items above.

---

## 14. The learned alternative (not in this repo)

A second answer to seller-vs-client was built and trained: a **fine-tuned ResNet18** on
person crops, instead of the HSV/keypoint rule. It is recorded here because the result
explains *why the rule was kept* — the code and weights stay local.

It was trained on a dataset that the rule engine **auto-labelled** — 806 crops from
153 tracks (501 seller / 305 client), class-weighted, 666 train / 140 val:

```
accuracy 99.29 %  (n=140)
              pred_client  pred_seller
true_client        24            1
true_seller         0          115
client  P=1.000  R=0.960  F1=0.980
seller  P=0.991  R=1.000  F1=0.996
```

Read that 99.29 % carefully: the validation split comes from the **same camera and the
same day** as training, so it measures "can a CNN reproduce the rule on this footage",
not "will it generalise to a new store". Final-code_v1 stays on the rule because the rule
is inspectable — when it is wrong, the keypoint dots show you why in one frame. The
classifier is the fallback worth reaching for when a store's uniform is not
colour-separable at all; ask the author for that branch.

---

## 15. Known limitations

- **Zone coordinates are camera-specific.** Every polygon in Final-code_v1.py is tuned to one
  1920×1080 view. Nothing works on a new camera until §7 is done.
- **The uniform must be colour-separable.** White shirt + black trousers, on footage where
  customers wear the same, defeats the cue. Lean on `SELLER_ZONES`, or move to the
  trained classifier (§14).
- **Standing staff outside a seller zone with occluded legs read as CLIENT.** No leg
  keypoints → no trouser cue → the zone override is the only fallback.
- **A returning customer is a new customer.** Entry counting is by pass, not by identity;
  someone who leaves and comes back is counted twice. A local experiment de-duplicates
  this with ReID embeddings, but its thresholds are untuned.
- **Interactions need a track id.** The entry counter is id-free, but interaction
  de-duplication is not — a customer whose id churns mid-conversation can restart their
  contact timer.
- **`DEBUG_ZONE` and `DEBUG_CALIB` are on by default.** Turn both off before delivering
  output video — the debug text is drawn into the pixels.
