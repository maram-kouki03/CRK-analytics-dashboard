#!/usr/bin/env python3
"""
pick_zones.py - click polygons over a video frame to define EXCLUSION ZONES
(e.g. mirrors). Detections whose feet fall inside a zone are ignored by the
pipeline, so reflections in mirrors never become fake tracks/counts.

Usage:
    python "pick_zones.py" ../testvid_playable.mp4            # frame 0
    python "pick_zones.py" ../testvid_playable.mp4 4080       # a specific frame

Controls:
    left-click   add a corner to the CURRENT polygon
    n            finish current polygon, start a NEW one  (one per mirror)
    u            undo last point
    s            print all polygons (paste into MIRROR_ZONES in bot-sort.py)
    q / ESC      quit (also prints)
"""
import sys
import cv2
import numpy as np
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

VIDEO = os.path.join(_HERE, "..", "testvid_playable.mp4")
FRAME = int(sys.argv[2]) if len(sys.argv) > 2 else 0

cap = cv2.VideoCapture(VIDEO)
# sequential read to the requested frame (seek can be corrupt on some files)
ok, frame = False, None
for i in range(FRAME + 1):
    ok, frame = cap.read()
    if not ok:
        break
cap.release()
if not ok or frame is None:
    print(f"Could not read frame {FRAME} from {VIDEO}")
    sys.exit(1)

polys = [[]]          # list of polygons; each is a list of (x, y)
WIN = "pick zones — click corners | n=new  u=undo  s=save  q=quit"


def redraw():
    vis = frame.copy()
    for pi, poly in enumerate(polys):
        col = (0, 0, 255) if pi == len(polys) - 1 else (0, 200, 0)
        for pt in poly:
            cv2.circle(vis, pt, 5, col, -1)
        if len(poly) >= 2:
            cv2.polylines(vis, [np.array(poly, np.int32)], pi != len(polys) - 1, col, 2)
        if poly:
            cv2.putText(vis, f"mirror {pi+1}", poly[0], cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
    cv2.imshow(WIN, vis)


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        polys[-1].append((x, y))
        redraw()


def dump():
    zones = [p for p in polys if len(p) >= 3]
    print("\n# paste this into bot-sort.py:")
    print("MIRROR_ZONES = [")
    for p in zones:
        print("    " + repr(p) + ",")
    print("]")


cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
cv2.setMouseCallback(WIN, on_mouse)
redraw()
while True:
    k = cv2.waitKey(20) & 0xFF
    if k in (ord('q'), 27):
        dump(); break
    elif k == ord('n'):
        if polys[-1]:
            polys.append([]); redraw()
    elif k == ord('u'):
        if polys[-1]:
            polys[-1].pop()
        elif len(polys) > 1:
            polys.pop()
        redraw()
    elif k == ord('s'):
        dump()
cv2.destroyAllWindows()
