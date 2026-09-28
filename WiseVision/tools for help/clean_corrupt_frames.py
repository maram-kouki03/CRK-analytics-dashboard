#!/usr/bin/env python3
"""
clean_corrupt_frames.py - rewrite a video with the HEVC decode-error frames dropped.

WHY: testvid has frames where the H.265 decoder lost its reference frame -- they
come out near-gray and flat with ghost macroblocks. They SURVIVE sequential decode
but poison the detection pipelines (phantom YOLO boxes, garbage ReID embeddings,
inflated client / PEC counts). This tool reads the source SEQUENTIALLY (no seeking,
so the decoder stays in sync), drops the corrupt frames, and writes a clean copy.
Point SC.py / seller_reid.py at the OUTPUT and no code change is needed.

Detector (calibrated on all 65k frames of testvid_playable.mp4):
  good frames  -> sat_mean ~38,  gray_frac ~0.13
  corrupt      -> sat_mean  <2,  gray_frac >0.94
A frame is dropped only if BOTH fire (near-gray AND flat), so a frame that is
merely dim OR merely low-texture is kept. Thresholds sit deep in the gap.

Usage:
  python "clean_corrupt_frames.py"                      # use the defaults below
  python "clean_corrupt_frames.py" INPUT.mp4 OUTPUT.mp4
"""
import os
import sys
import time
import cv2
import numpy as np

# --- defaults (override on the command line) ----------------------------------
DEFAULT_IN  = r"C:\Users\MSI\Desktop\WiseVision\testvid_playable.mp4"
DEFAULT_OUT = r"C:\Users\MSI\Desktop\WiseVision\testvid_clean.mp4"

# --- corrupt-frame detector (same thresholds as the pipelines) ----------------
CORRUPT_SAT_MAX  = 8.0     # mean HSV saturation below this => near-gray (no color)
CORRUPT_GRAY_MIN = 0.60    # frac of pixels within +-12 of median luma above => flat


def frame_is_corrupt(frame: np.ndarray) -> bool:
    """True for HEVC decode-error frames (near-gray AND flat). Cheap: 320x180."""
    small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
    if float(cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[..., 1].mean()) >= CORRUPT_SAT_MAX:
        return False
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    flat = float(np.mean(np.abs(gray.astype(int) - np.median(gray)) <= 12))
    return flat > CORRUPT_GRAY_MIN


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IN
    dst = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT

    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        print(f"ERROR: cannot open '{src}'")
        return
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"[in ] {src}")
    print(f"      {width}x{height} @ {fps:.3f} fps, ~{total} frames")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(dst, fourcc, fps, (width, height))
    if not writer.isOpened():
        print(f"ERROR: cannot open writer for '{dst}'")
        cap.release()
        return

    kept = dropped = idx = 0
    t0 = time.perf_counter()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_is_corrupt(frame):
            dropped += 1
        else:
            writer.write(frame)
            kept += 1
        idx += 1
        if idx % 2000 == 0:
            pct = 100.0 * idx / total if total else 0.0
            print(f"  {idx:>6}/{total} ({pct:4.1f}%)  kept={kept} dropped={dropped}")
    cap.release()
    writer.release()

    elapsed = time.perf_counter() - t0
    print(f"[out] {dst}")
    print(f"      read={idx}  kept={kept}  dropped={dropped} "
          f"({100.0 * dropped / max(idx,1):.1f}% corrupt)  in {elapsed:.0f}s")
    print(f"      clean duration ~ {kept / fps:.1f}s (was {idx / fps:.1f}s)")


if __name__ == "__main__":
    main()
