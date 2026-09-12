"""Object-detection wrapper (Section 5.3): the one place this project
touches a generic object detector (YOLO) before everything downstream
becomes track-limits-specific geometry. Kept deliberately thin -- a
detector swap only ever touches this file.

load_yolo_model defers the actual `ultralytics` import to call time,
not module import time: this module (and everything that imports it) is
importable and testable in an environment with no ultralytics/torch
installed, same as the rest of src/vision/.
"""
from __future__ import annotations

#: COCO class ids this pipeline treats as vehicles: car, motorcycle, bus, truck.
VEHICLE_CLASS_IDS = {2, 3, 5, 7}


def iter_vehicle_detections(results, conf_threshold: float):
    """Yield every detected box that is both a vehicle class and at/above
    conf_threshold, in the detector's own order. Never picks a winner --
    that's best_vehicle_detection's job, kept separate so a caller that
    wants every vehicle in frame (the uncalibrated demo-zone path, which
    draws all of them) isn't forced through a single-winner API.
    """
    for box in results.boxes:
        if int(box.cls) not in VEHICLE_CLASS_IDS:
            continue
        conf = float(box.conf)
        if conf < conf_threshold:
            continue
        yield box


def best_vehicle_detection(results, conf_threshold: float):
    """The single highest-confidence vehicle detection at/above
    conf_threshold, or None if there isn't one. Ties keep whichever was
    seen first (results.boxes' own order).
    """
    best_box, best_conf = None, -1.0
    for box in iter_vehicle_detections(results, conf_threshold):
        conf = float(box.conf)
        if conf <= best_conf:
            continue
        best_box, best_conf = box, conf
    return best_box


def load_yolo_model(weights: str = "yolov8n.pt"):
    """Lazily imports ultralytics so geometry-only callers (tests,
    calibration, the rest of src/vision/) never need ultralytics/torch
    installed at all -- only actually running detection does.
    """
    from ultralytics import YOLO

    return YOLO(weights)
