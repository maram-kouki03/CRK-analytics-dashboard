import os
import glob
import time
from pathlib import Path

import cv2
import numpy as np
np.float = float

import torch
from ultralytics import YOLO
import supervision as sv
from boxmot.trackers.tracker_zoo import create_tracker

SOURCE_VIDEO_PATH = "CRK01.mp4"
TARGET_VIDEO_PATH = "SC_output11.mp4"

MODEL_NAME = "yolo11m.pt"
REID_MODEL = "osnet_ain_x1_0_msmt17.pt"
DEVICE         = "cuda:0" if torch.cuda.is_available() else "cpu"
HALF_PRECISION = torch.cuda.is_available()

DETECT_CONF     = 0.1
CONF_CLIENT     = 0.2
PERSON_CLASS_ID = 0
SKIP            = 3

TRACK_BUFFER         = 180
APPEARANCE_THRESH    = 0.3
PROXIMITY_THRESH     = 0.8
MATCH_THRESH         = 0.8
CMC_METHOD           = "ecc"
TRACK_HIGH_THRESH    = 0.4
TRACK_LOW_THRESH     = 0.1
NEW_TRACK_THRESH     = 0.2
APPEARANCE_EMA_ALPHA = 0.95

USE_REF_COLORS  = False
SELLER_REF_DIR  = "reference_image"
UNIFORM_BAND_LO = np.array([18,  0,  51])
UNIFORM_BAND_HI = np.array([49, 54, 240])
COLOR_PCT_LO = 5
COLOR_PCT_HI = 95
COLOR_MARGIN = np.array([4, 15, 30])
COLOR_TAKE   = 0.30
WHITE_MIN    = 0.25
SELLER_VOTES = 2

BEIGE_H_MIN, BEIGE_H_MAX = 22, 55
BEIGE_S_MAX = 95
BEIGE_V_MIN = 75
WHITE_S_MAX = 80
WHITE_V_MIN = 85

SEED_SECONDS   = 3.0
SEED_BEIGE_MIN = 0.05

ENTER_ZONE_1 = [
    [(1909, 708), (1909, 1068), (1715, 1065), (1822, 685), (1908, 708)]
    
]
ENTER_ZONE_2 = [
    [(1682, 1055), (1790, 680), (1732, 663), (1602, 1066), (1686, 1053)]
    
]
ENTER_ZONE_FRAC = 0.11
_ENTER_POLYS_1 = [np.array(z, np.int32) for z in ENTER_ZONE_1 if len(z) >= 3]
_ENTER_POLYS_2 = [np.array(z, np.int32) for z in ENTER_ZONE_2 if len(z) >= 3]
ZONE_MATCH_DIST = 170
ZONE_TTL        = 20

ENTRY_REVERT_SECS = 6.0

PEC_PROX_DIST   = 200
PEC_MIN_SECS    = 8.0
PEC_GRACE_SECS  = 12
PEC_FOLLOW_DIST = 160
PEC_EMA         = 0.5

MIRROR_ZONES = [
    [(36, 125), (195, 59), (419, 635), (168, 745), (34, 131)],
    [(1732, 3), (1888, 4), (1788, 493), (1654, 448), (1730, 8)],
    [(904, 3), (1124, 4), (1155, 61), (1161, 240), (929, 276), (902, 10)],
]
SELLER_ZONES = [
    [(198, 851), (478, 696), (1001, 1001), (1086, 1068), (325, 1068), (196, 854)],
    [(964, 887), (1416, 893), (1428, 1068), (894, 1069), (959, 888)],
    [(161, 780), (471, 674), (494, 704), (201, 847), (161, 786)],
     [(1008, 255), (992, 140), (1152, 146), (1159, 247), (1008, 255)],
    [(695, 666), (592, 565), (528, 381), (705, 323), (732, 387), (698, 665)]
]
SELLER_ZONE_FRAC = 0.70
IGNORE_ZONES = [
            [(1789, 663), (1838, 680), (1819, 768), (1769, 750), (1788, 665)],
            [(404, 753), (649, 1068), (914, 941), (588, 651), (408, 750)],
            [(502, 674), (471, 661), (316, 740), (329, 794), (501, 681)]
]
_MIRROR_POLYS = [np.array(z, np.int32) for z in MIRROR_ZONES if len(z) >= 3]
_SELLER_POLYS = [np.array(z, np.int32) for z in SELLER_ZONES if len(z) >= 3]
_IGNORE_POLYS = [np.array(z, np.int32) for z in IGNORE_ZONES if len(z) >= 3]

DEBUG_CALIB = True
MAX_FRAMES  = 0

_MAX_PIX = 400_000
_BG_H_MIN, _BG_H_MAX = BEIGE_H_MIN, BEIGE_H_MAX
_BG_S_MAX, _BG_V_MIN = BEIGE_S_MAX, BEIGE_V_MIN


def _patch_appearance_ema(alpha: float):
    import boxmot.trackers.bbox.botsort.botsort_track as bt
    if getattr(bt.STrack, "_ema_patched", False):
        bt.STrack.alpha = alpha
        return
    _orig_init = bt.STrack.__init__
    def _init(self, *a, **k):
        _orig_init(self, *a, **k)
        self.alpha = alpha
    bt.STrack.__init__ = _init
    bt.STrack._ema_patched = True


def build_botsort():
    _patch_appearance_ema(APPEARANCE_EMA_ALPHA)
    tuning = dict(
        track_high_thresh=TRACK_HIGH_THRESH,
        track_low_thresh=TRACK_LOW_THRESH,
        new_track_thresh=NEW_TRACK_THRESH,
        track_buffer=TRACK_BUFFER,
        match_thresh=MATCH_THRESH,
        proximity_thresh=PROXIMITY_THRESH,
        appearance_thresh=APPEARANCE_THRESH,
        cmc_method=CMC_METHOD,
    )
    return create_tracker(
        tracker_type="botsort",
        reid_weights=Path(REID_MODEL),
        device=torch.device(DEVICE),
        half=HALF_PRECISION,
        per_class=False,
        evolve_param_dict=tuning,
    )


def signed_dist_to_line(point, ls: sv.Point, le: sv.Point) -> float:
    dx, dy = le.x - ls.x, le.y - ls.y
    cross = dx * (point[1] - ls.y) - dy * (point[0] - ls.x)
    return cross / (np.hypot(dx, dy) + 1e-9)


def _feet_in_polys(xyxy: np.ndarray, polys) -> np.ndarray:
    if not polys or len(xyxy) == 0:
        return np.zeros((len(xyxy),), dtype=bool)
    feet = np.c_[(xyxy[:, 0] + xyxy[:, 2]) / 2.0, xyxy[:, 3]]
    mask = np.zeros((len(xyxy),), dtype=bool)
    for i, (fx, fy) in enumerate(feet):
        mask[i] = any(cv2.pointPolygonTest(p, (float(fx), float(fy)), False) >= 0
                      for p in polys)
    return mask


def in_mirror_zone(xyxy: np.ndarray) -> np.ndarray:
    return _feet_in_polys(xyxy, _MIRROR_POLYS)


def in_ignore_zone(xyxy: np.ndarray) -> np.ndarray:
    return _feet_in_polys(xyxy, _IGNORE_POLYS)


def in_seller_zone(bbox) -> bool:
    if not _SELLER_POLYS:
        return False
    x1, y1, x2, y2 = (float(v) for v in bbox)
    if x2 <= x1 or y2 <= y1:
        return False
    inside = total = 0
    for px in np.linspace(x1, x2, 6):
        for py in np.linspace(y1, y2, 6):
            total += 1
            if any(cv2.pointPolygonTest(poly, (px, py), False) >= 0 for poly in _SELLER_POLYS):
                inside += 1
    return (inside / total) >= SELLER_ZONE_FRAC


def box_overlap_frac(bbox, polys) -> float:
    if not polys:
        return 0.0
    x1, y1, x2, y2 = (float(v) for v in bbox)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inside = total = 0
    for px in np.linspace(x1, x2, 6):
        for py in np.linspace(y1, y2, 6):
            total += 1
            if any(cv2.pointPolygonTest(poly, (px, py), False) >= 0 for poly in polys):
                inside += 1
    return inside / total if total else 0.0


def torso_white_ratio(frame: np.ndarray, bbox) -> float:
    x1, y1, x2, y2 = (int(v) for v in bbox)
    h, w = y2 - y1, x2 - x1
    if h <= 0 or w <= 0:
        return 0.0
    ty1 = max(0, y1 + int(0.15 * h)); ty2 = max(0, y1 + int(0.45 * h))
    tx1 = max(0, x1 + int(0.20 * w)); tx2 = max(0, x2 - int(0.20 * w))
    crop = frame[ty1:ty2, tx1:tx2]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 1] <= WHITE_S_MAX) & (hsv[:, :, 2] >= WHITE_V_MIN)
    return float(white.mean())


def beige_pants_ratio(frame: np.ndarray, bbox) -> float:
    x1, y1, x2, y2 = (int(v) for v in bbox)
    h, w = y2 - y1, x2 - x1
    if h <= 0 or w <= 0:
        return 0.0
    ly1 = max(0, y1 + int(0.55 * h)); ly2 = max(0, y1 + int(0.88 * h))
    lx1 = max(0, x1 + int(0.25 * w)); lx2 = max(0, x2 - int(0.25 * w))
    crop = frame[ly1:ly2, lx1:lx2]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    beige = ((hsv[:, :, 0] >= BEIGE_H_MIN) & (hsv[:, :, 0] <= BEIGE_H_MAX) &
             (hsv[:, :, 1] <= BEIGE_S_MAX) & (hsv[:, :, 2] >= BEIGE_V_MIN))
    return float(beige.mean())


def lower_body_hsv(frame: np.ndarray, bbox):
    x1, y1, x2, y2 = (int(v) for v in bbox)
    h, w = y2 - y1, x2 - x1
    if h <= 0 or w <= 0:
        return None
    ly1 = max(0, y1 + int(0.55 * h)); ly2 = max(0, y1 + int(0.88 * h))
    lx1 = max(0, x1 + int(0.25 * w)); lx2 = max(0, x2 - int(0.25 * w))
    crop = frame[ly1:ly2, lx1:lx2]
    if crop.size == 0:
        return None
    return cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.int16)


class UniformModel:
    def __init__(self):
        self.pix = []
        self._npix = 0
        self._bounds = None
        self._center = None
        self._fixed = False

    def set_fixed_band(self, lo, hi):
        lo = np.asarray(lo, dtype=float); hi = np.asarray(hi, dtype=float)
        self._bounds = (lo, hi)
        self._center = (lo + hi) / 2.0
        self._fixed = True

    def _beige_pixels(self, frame, bbox):
        px = lower_body_hsv(frame, bbox)
        if px is None or len(px) == 0:
            return None
        h, s, v = px[:, 0], px[:, 1], px[:, 2]
        m = (h >= _BG_H_MIN) & (h <= _BG_H_MAX) & (s <= _BG_S_MAX) & (v >= _BG_V_MIN)
        keep = px[m]
        return keep if len(keep) else None

    def _collect(self, frame, bbox):
        if self._fixed or self._npix >= _MAX_PIX:
            return
        keep = self._beige_pixels(frame, bbox)
        if keep is not None:
            self.pix.append(keep)
            self._npix += len(keep)
            self._bounds = None

    def add_seed_sample(self, frame, bbox):
        if beige_pants_ratio(frame, bbox) >= SEED_BEIGE_MIN:
            self._collect(frame, bbox)

    def learn_from_dir(self, ref_dir: str):
        paths = sorted(glob.glob(os.path.join(ref_dir, "*.png")) +
                       glob.glob(os.path.join(ref_dir, "*.jpg")))
        n = 0
        for p in paths:
            img = cv2.imread(p)
            if img is None:
                continue
            h, w = img.shape[:2]
            box = (0, 0, w, h)
            if beige_pants_ratio(img, box) < SEED_BEIGE_MIN:
                continue
            before = self._npix
            self._collect(img, box)
            n += int(self._npix > before)
        print(f"[UNIFORM] learned beige from {n} crop(s) in '{ref_dir}' "
              f"({self._npix} pixels)")

    def _fit(self):
        allpx = np.concatenate(self.pix, axis=0)
        lo = np.percentile(allpx, COLOR_PCT_LO, axis=0) - COLOR_MARGIN
        hi = np.percentile(allpx, COLOR_PCT_HI, axis=0) + COLOR_MARGIN
        lo = np.maximum(lo, [0, 0, 0])
        hi = np.minimum(hi, [180, 255, 255])
        self._bounds = (lo, hi)
        self._center = np.median(allpx, axis=0)

    def bounds(self):
        if self._bounds is None and self.pix:
            self._fit()
        return self._bounds

    def color_ratio(self, frame, bbox) -> float:
        px = lower_body_hsv(frame, bbox)
        if px is None or len(px) == 0:
            return 0.0
        b = self.bounds()
        if b is None:
            return beige_pants_ratio(frame, bbox)
        lo, hi = b
        mask = np.all((px >= lo) & (px <= hi), axis=1)
        return float(mask.mean())

    def is_uniform(self, frame, bbox):
        color = self.color_ratio(frame, bbox)
        white = torso_white_ratio(frame, bbox)
        return (color >= COLOR_TAKE and white >= WHITE_MIN), color, white


def draw_frame(frame, persons, entry_count, pec_count=0):
    SELLER_COLOR = (0, 0, 255)
    CLIENT_COLOR = (0, 200, 0)
    for bbox, role in persons:
        x1, y1, x2, y2 = map(int, bbox)
        color = SELLER_COLOR if role == "SELLER" else CLIENT_COLOR
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        (tw, th), _ = cv2.getTextSize(role, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
        cv2.putText(frame, role, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    for poly in _MIRROR_POLYS:
        cv2.polylines(frame, [poly], True, (255, 0, 255), 2, cv2.LINE_AA)
    for poly in _SELLER_POLYS:
        cv2.polylines(frame, [poly], True, (0, 0, 255), 2, cv2.LINE_AA)
    for poly in _IGNORE_POLYS:
        cv2.polylines(frame, [poly], True, (128, 128, 128), 2, cv2.LINE_AA)
    for poly in _ENTER_POLYS_1:
        cv2.polylines(frame, [poly], True, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "1", tuple(poly[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
    for poly in _ENTER_POLYS_2:
        cv2.polylines(frame, [poly], True, (255, 200, 0), 2, cv2.LINE_AA)
        cv2.putText(frame, "2", tuple(poly[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 200, 0), 2)
    cv2.putText(frame, f"Entries: {entry_count}  PEC: {pec_count}",
                (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    return frame


def main():
    print("=" * 50)
    if torch.cuda.is_available():
        print(f"[GPU] {torch.cuda.get_device_name(0)} | CUDA {torch.version.cuda}")
    else:
        print("[GPU] running on CPU.")
    print("=" * 50)

    model = YOLO(MODEL_NAME)
    model.to(DEVICE)
    model.fuse()

    botsort = build_botsort()
    uniform = UniformModel()
    if USE_REF_COLORS:
        uniform.learn_from_dir(SELLER_REF_DIR)
    else:
        uniform.set_fixed_band(UNIFORM_BAND_LO, UNIFORM_BAND_HI)
        print(f"[UNIFORM] using baked-in band  LO={UNIFORM_BAND_LO.tolist()}  "
              f"HI={UNIFORM_BAND_HI.tolist()}  (no reference_image needed)")

    video_info = sv.VideoInfo.from_video_path(SOURCE_VIDEO_PATH)
    fps        = video_info.fps
    generator  = sv.get_video_frames_generator(SOURCE_VIDEO_PATH)

    seller_tracks = set()
    seller_votes = {}
    entry_count = 0
    zone_objs = []
    entry_by_tid = {}

    pec_active = False
    pec_count = 0
    pec_start_t = None
    pec_last_t = None
    pec_seen_secs = 0.0
    pec_pos = None
    pec_counted = False
    pec_durations = []

    stats = {}
    last_persons = []
    processed_frame_idx = -1
    frame_ms_total = 0.0
    timed_frames = 0

    with sv.VideoSink(TARGET_VIDEO_PATH, video_info) as sink:
        for frame_idx, frame in enumerate(generator):
            if frame_idx % SKIP != 0:
                draw_frame(frame, last_persons, entry_count, pec_count)
                sink.write_frame(frame)
                continue
            if MAX_FRAMES and processed_frame_idx + 1 >= MAX_FRAMES:
                break

            processed_frame_idx += 1
            timestamp = frame_idx / fps
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            _t0 = time.perf_counter()

            results = model(frame, conf=DETECT_CONF, classes=[PERSON_CLASS_ID],
                            iou=0.5, imgsz=640, device=DEVICE,
                            half=HALF_PRECISION, verbose=False)
            detections = sv.Detections(
                xyxy=results[0].boxes.xyxy.cpu().numpy(),
                confidence=results[0].boxes.conf.cpu().numpy(),
                class_id=results[0].boxes.cls.cpu().numpy().astype(int),
            )

            if _MIRROR_POLYS and len(detections.xyxy) > 0:
                detections = detections[~in_mirror_zone(detections.xyxy)]
            if _IGNORE_POLYS and len(detections.xyxy) > 0:
                detections = detections[~in_ignore_zone(detections.xyxy)]

            n_det = len(detections.xyxy)
            if n_det > 0:
                dets = np.hstack([
                    detections.xyxy,
                    detections.confidence[:, None],
                    detections.class_id[:, None].astype(float),
                ])
            else:
                dets = np.empty((0, 6))
            tracks = botsort.update(dets, frame)
            tracker_ids = [None] * n_det
            if tracks is not None and len(tracks) > 0:
                for tr in tracks:
                    j = int(tr[7])
                    if 0 <= j < n_det:
                        tracker_ids[j] = int(tr[4])

            seeding = timestamp <= SEED_SECONDS

            persons = []
            for i in range(n_det):
                bbox = detections.xyxy[i]
                conf = float(detections.confidence[i])
                tid  = tracker_ids[i]

                if seeding:
                    role = "SELLER"
                    uniform.add_seed_sample(frame, bbox)
                    if tid is not None:
                        seller_tracks.add(tid)
                else:
                    is_unif, color, white = uniform.is_uniform(frame, bbox)
                    has_white = white >= WHITE_MIN
                    if not has_white:
                        role = "CLIENT"
                    elif tid is not None:
                        if is_unif:
                            seller_votes[tid] = seller_votes.get(tid, 0) + 1
                            if seller_votes[tid] >= SELLER_VOTES:
                                seller_tracks.add(tid)
                        role = "SELLER" if tid in seller_tracks else "CLIENT"
                    else:
                        role = "SELLER" if is_unif else "CLIENT"
                    if DEBUG_CALIB and tid is not None:
                        st = stats.setdefault(tid, {"frames": 0, "seller": 0,
                                                    "color": 0.0, "white": 0.0})
                        st["frames"] += 1
                        st["seller"] += int(role == "SELLER")
                        st["color"] = max(st["color"], color)
                        st["white"] = max(st["white"], white)

                if in_seller_zone(bbox):
                    role = "SELLER"
                    if tid is not None:
                        seller_tracks.add(tid)

                if role == "SELLER" and tid is not None and tid in entry_by_tid:
                    if timestamp - entry_by_tid[tid] <= ENTRY_REVERT_SECS and entry_count > 0:
                        entry_count -= 1
                        print(f"[CNT] f{processed_frame_idx} REVERT -1 (tid {tid} became "
                              f"SELLER {timestamp - entry_by_tid[tid]:.1f}s after entry) "
                              f"-> count={entry_count}")
                    del entry_by_tid[tid]

                if role == "CLIENT" and conf < CONF_CLIENT:
                    continue
                persons.append((bbox, role))

                if role == "CLIENT":
                    f1 = box_overlap_frac(bbox, _ENTER_POLYS_1)
                    f2 = box_overlap_frac(bbox, _ENTER_POLYS_2)
                    cz = 0
                    if f1 >= ENTER_ZONE_FRAC or f2 >= ENTER_ZONE_FRAC:
                        cz = 1 if f1 >= f2 else 2
                    cx = (bbox[0] + bbox[2]) / 2.0
                    cy = (bbox[1] + bbox[3]) / 2.0
                    pf = processed_frame_idx
                    best = None; best_dist = ZONE_MATCH_DIST
                    for o in zone_objs:
                        if pf - o[4] <= ZONE_TTL:
                            dd = np.hypot(cx - o[0], cy - o[1])
                            if dd < best_dist:
                                best_dist = dd; best = o
                    if best is None:
                        if cz != 0:
                            zone_objs.append([cx, cy, cz, False, pf])
                    else:
                        prev_zone = best[2]
                        if cz != 0 and cz != prev_zone:
                            if prev_zone == 1 and cz == 2 and not best[3]:
                                entry_count += 1
                                best[3] = True
                                if tid is not None:
                                    entry_by_tid[tid] = timestamp
                                print(f"[CNT] f{pf} ENTER (1->2) at ({cx:.0f},{cy:.0f}) "
                                      f"-> count={entry_count}")
                            best[2] = cz
                        best[0], best[1], best[4] = cx, cy, pf

            zone_objs = [o for o in zone_objs if processed_frame_idx - o[4] <= ZONE_TTL]
            entry_by_tid = {t: ts for t, ts in entry_by_tid.items()
                            if timestamp - ts <= ENTRY_REVERT_SECS}

            seller_boxes = [b for b, r in persons if r == "SELLER"]
            if seller_boxes:
                contacts = []
                for b, r in persons:
                    if r != "CLIENT":
                        continue
                    cx1, cy1, cx2, cy2 = b
                    for sx1, sy1, sx2, sy2 in seller_boxes:
                        gap_x = max(0, max(cx1, sx1) - min(cx2, sx2))
                        gap_y = max(0, max(cy1, sy1) - min(cy2, sy2))
                        if np.hypot(gap_x, gap_y) < PEC_PROX_DIST:
                            contacts.append(((cx1 + cx2) / 2, (cy1 + cy2) / 2))
                            break

                if pec_active:
                    best = None; best_d = PEC_FOLLOW_DIST
                    for ccx, ccy in contacts:
                        dd = np.hypot(ccx - pec_pos[0], ccy - pec_pos[1])
                        if dd < best_d:
                            best_d, best = dd, (ccx, ccy)
                    if best is not None:
                        pec_pos = (PEC_EMA * pec_pos[0] + (1 - PEC_EMA) * best[0],
                                   PEC_EMA * pec_pos[1] + (1 - PEC_EMA) * best[1])
                        pec_last_t = timestamp
                        pec_seen_secs += SKIP / fps
                        if not pec_counted and pec_seen_secs >= PEC_MIN_SECS:
                            pec_count += 1
                            pec_counted = True
                    elif timestamp - pec_last_t > PEC_GRACE_SECS:
                        if pec_counted:
                            pec_durations.append(pec_seen_secs)
                        pec_active = False; pec_pos = None
                else:
                    if contacts:
                        served = min(contacts, key=lambda c: min(
                            (c[0] - (s[0] + s[2]) / 2) ** 2 + (c[1] - (s[1] + s[3]) / 2) ** 2
                            for s in seller_boxes))
                        pec_active = True; pec_counted = False
                        pec_pos = served
                        pec_start_t = timestamp; pec_last_t = timestamp
                        pec_seen_secs = 0.0

            draw_frame(frame, persons, entry_count, pec_count)
            sink.write_frame(frame)
            last_persons = persons

            if torch.cuda.is_available():
                torch.cuda.synchronize()
            frame_ms_total += (time.perf_counter() - _t0) * 1000.0
            timed_frames   += 1

    if pec_active and pec_counted:
        pec_durations.append(pec_seen_secs)
    avg_pec = (sum(pec_durations) / len(pec_durations)) if pec_durations else 0.0

    del model, botsort
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    if DEBUG_CALIB:
        b = uniform.bounds()
        if b is not None:
            lo, hi = b
            print(f"\n[CALIB] uniform beige band  H:[{lo[0]:.0f},{hi[0]:.0f}] "
                  f"S:[{lo[1]:.0f},{hi[1]:.0f}] V:[{lo[2]:.0f},{hi[2]:.0f}]")

    print("\n========== RESULT ==========")
    print(f"Processed frames : {timed_frames}")
    print(f"Clients entered  : {entry_count}")
    print(f"PEC events       : {pec_count}")
    print(f"Avg interaction  : {avg_pec:.1f} s")
    print(f"Output video     : {TARGET_VIDEO_PATH}")
    if timed_frames > 0:
        print(f"Full pipeline    : {frame_ms_total / timed_frames:.1f} ms/frame "
              f"({timed_frames / (frame_ms_total / 1000.0):.1f} FPS)")
    print("============================")


if __name__ == "__main__":
    main()
