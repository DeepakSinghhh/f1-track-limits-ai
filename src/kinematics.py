import numpy as np

WHEELS_BODY = np.array([[1.8, 0.8], [1.8, -0.8], [-1.8, 0.8], [-1.8, -0.8]])

def get_wheels_world(car_world_pos, yaw_rad):
    c, s = np.cos(yaw_rad), np.sin(yaw_rad)
    R = np.array([[c, -s], [s, c]])
    return car_world_pos + (R @ WHEELS_BODY.T).T
