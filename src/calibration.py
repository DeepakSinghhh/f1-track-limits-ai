import cv2
import numpy as np

class CameraCalibrator:
    def __init__(self):
        src_pts = np.float32([[200, 400], [1000, 400], [1200, 700], [100, 700]])
        dst_pts = np.float32([[20, 0], [40, 0], [40, 15], [20, 15]])
        self.H, _ = cv2.findHomography(src_pts, dst_pts)

    def pixel_to_world(self, u, v):
        pt = np.array([u, v, 1.0])
        world_pt = self.H @ pt
        return world_pt[:2] / world_pt[2] if world_pt[2] != 0 else np.array([0.0, 0.0])
