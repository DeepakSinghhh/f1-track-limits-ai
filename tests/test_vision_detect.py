"""iter_vehicle_detections/best_vehicle_detection were previously inline
in src/detector.py, coupled to a real ultralytics Results object and
never unit tested on their own -- only exercised (never, in this
sandbox) through a full YOLO run. Extracting them to src/vision/detect.py
makes them testable against a tiny fake that mimics just the two
attributes this code actually reads (box.cls, box.conf) -- no
ultralytics/torch import required.
"""
import pytest

from src.vision.detect import VEHICLE_CLASS_IDS, best_vehicle_detection, iter_vehicle_detections, load_yolo_model


class FakeBox:
    def __init__(self, cls: int, conf: float):
        self.cls = cls
        self.conf = conf


class FakeResults:
    def __init__(self, boxes):
        self.boxes = boxes


def test_iter_vehicle_detections_filters_by_class_and_confidence():
    boxes = [
        FakeBox(cls=2, conf=0.9),   # car, passes
        FakeBox(cls=0, conf=0.99),  # person -- not a vehicle class
        FakeBox(cls=7, conf=0.3),   # truck, below threshold
        FakeBox(cls=5, conf=0.6),   # bus, passes
    ]
    kept = list(iter_vehicle_detections(FakeResults(boxes), conf_threshold=0.5))
    assert kept == [boxes[0], boxes[3]]


def test_iter_vehicle_detections_covers_every_configured_vehicle_class():
    boxes = [FakeBox(cls=c, conf=1.0) for c in VEHICLE_CLASS_IDS]
    kept = list(iter_vehicle_detections(FakeResults(boxes), conf_threshold=0.5))
    assert kept == boxes


def test_best_vehicle_detection_picks_highest_confidence():
    low = FakeBox(cls=2, conf=0.6)
    high = FakeBox(cls=2, conf=0.95)
    mid = FakeBox(cls=3, conf=0.8)
    best = best_vehicle_detection(FakeResults([low, high, mid]), conf_threshold=0.5)
    assert best is high


def test_best_vehicle_detection_ties_keep_the_first_seen():
    first = FakeBox(cls=2, conf=0.8)
    second = FakeBox(cls=3, conf=0.8)
    best = best_vehicle_detection(FakeResults([first, second]), conf_threshold=0.5)
    assert best is first


def test_best_vehicle_detection_returns_none_when_nothing_qualifies():
    boxes = [FakeBox(cls=0, conf=0.99), FakeBox(cls=2, conf=0.1)]
    assert best_vehicle_detection(FakeResults(boxes), conf_threshold=0.5) is None


def test_best_vehicle_detection_returns_none_for_empty_results():
    assert best_vehicle_detection(FakeResults([]), conf_threshold=0.5) is None


def test_load_yolo_model_defers_the_ultralytics_import():
    # This module (and every test above) importing cleanly already proves
    # `import src.vision.detect` doesn't require ultralytics. This proves
    # the other half: the import really is deferred to call time, and
    # fails with ImportError (not some other error from a botched
    # deferral) when ultralytics genuinely isn't installed.
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError):
            load_yolo_model()
    else:
        pytest.skip("ultralytics is installed in this environment; nothing to assert here")
