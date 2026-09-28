#!/usr/bin/env python3
"""
split_montage.py - cut a horizontal crop-montage (e.g. testvid_crops/people.png)
into its individual person crops and save them as separate PNGs, so each becomes
ONE clean row in the ReID seller gallery (build_seller_reid_gallery embeds each
file as a single crop -- a whole strip would embed as one garbage 'merged' vector).

Usage:
    python "tools for help/split_montage.py" testvid_crops/people.png reference_image
    python "tools for help/split_montage.py" <montage.png> <out_dir> [prefix]

Separator columns (near-uniform, between crops) are detected automatically.
"""
import os
import sys
import cv2
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT  = os.path.join(_HERE, "..")

src     = sys.argv[1] if len(sys.argv) > 1 else "testvid_crops/people.png"
out_dir = sys.argv[2] if len(sys.argv) > 2 else "bot-sort-version/reference_image"
prefix  = sys.argv[3] if len(sys.argv) > 3 else os.path.splitext(os.path.basename(src))[0]

src_path = src if os.path.isabs(src) else os.path.join(ROOT, src)
out_path = out_dir if os.path.isabs(out_dir) else os.path.join(ROOT, out_dir)

img = cv2.imread(src_path)
if img is None:
    print(f"[ERR] could not read {src_path}")
    sys.exit(1)
H, W = img.shape[:2]
os.makedirs(out_path, exist_ok=True)

# A separator column is near-uniform top-to-bottom (very low std). Real crop
# content always has high vertical std (person + background detail), so the two
# are cleanly bimodal -- a FIXED low threshold is far more robust than an
# adaptive percentile (which would cut through uniform shirt/wall columns).
col_std = img.std(axis=(0, 2))
SEP_THR = float(sys.argv[4]) if len(sys.argv) > 4 else 15.0
is_sep  = col_std < SEP_THR

# group consecutive non-separator columns into crop spans
spans = []
i = 0
while i < W:
    if not is_sep[i]:
        j = i
        while j < W and not is_sep[j]:
            j += 1
        if j - i >= 20:                 # ignore slivers narrower than 20px
            spans.append((i, j))
        i = j
    else:
        i += 1

print(f"[INFO] {src_path}  {W}x{H}  ->  {len(spans)} crop(s)  (sep_thr={SEP_THR:.1f})")
n = 0
for k, (x0, x1) in enumerate(spans):
    crop = img[:, x0:x1]
    # trim flat rows (top/bottom padding) the same way
    row_std = crop.std(axis=(1, 2))
    rows = np.where(row_std >= SEP_THR)[0]
    if len(rows) >= 20:
        crop = crop[rows[0]:rows[-1] + 1]
    if crop.shape[0] < 40 or crop.shape[1] < 20:
        continue
    name = f"{prefix}_{k}.png"
    cv2.imwrite(os.path.join(out_path, name), crop)
    print(f"   wrote {name}  ({crop.shape[1]}x{crop.shape[0]})")
    n += 1
print(f"[DONE] {n} crop(s) -> {out_path}")
