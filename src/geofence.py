import numpy as np
from matplotlib.path import Path

class GeofenceEngine:
    def __init__(self):
        self.poly = np.array([[26, 8.5], [34, 8.5], [34, 12], [26, 12]])

    def check_violation(self, wheels_world):
        return Path(self.poly).contains_points(wheels_world).any()

class TrackLimitTracker:
    def __init__(self):
        self.consecutive = 0
        self.strikes = 0
        self.in_event = False

    def update(self, is_violating):
        incident, penalty = False, False
        if is_violating:
            self.consecutive += 1
            if self.consecutive >= 4 and not self.in_event:
                self.in_event = True
                self.strikes += 1
                incident = True
                if self.strikes > 3: penalty = True
        else:
            self.consecutive = 0
            self.in_event = False
        return incident, penalty, self.strikes
