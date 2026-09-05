import cv2
import numpy as np
from ultralytics import YOLO
from src.geofence import TrackLimitTracker

class TrackLimitDetector:
    def __init__(self):
        self.model = YOLO("yolov8n.pt")
        self.tracker = TrackLimitTracker()
        self.demo_zone = None 

    def process_frame(self, frame, frame_id):
        h, w = frame.shape[:2]
        
        # 1. Create a virtual Track Limit Zone on the right side of the screen
        if self.demo_zone is None:
            self.demo_zone = np.array([[w//2, h//2], [w, h//2], [w, h], [w//3 + 50, h]])

        # 2. Draw the translucent Red Penalty Zone & HUD on the video
        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.demo_zone], (0, 0, 255))
        cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)
        cv2.putText(frame, "FIA TRACK LIMIT SENSOR: ACTIVE", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.polylines(frame, [self.demo_zone], isClosed=True, color=(0, 0, 255), thickness=2)

        results = self.model(frame, verbose=False)[0]
        incidents = []
        
        for box in results.boxes:
            if int(box.cls) in [2, 3, 5, 7]: # Targets vehicles
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                u, v = int((x1 + x2) / 2), y2  # Bottom-center of the car (tires)
                
                # 3. Check if the car's tires cross into our visual red zone
                violating = cv2.pointPolygonTest(self.demo_zone, (u, v), False) >= 0
                incident, penalty, strikes = self.tracker.update(violating)

                # 4. Change bounding box color dynamically (Green = Safe, Red = Penalty)
                color = (0, 0, 255) if violating else (0, 255, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.circle(frame, (u, v), 6, color, -1)
                
                status_text = "WARNING: OFF TRACK" if violating else "TRACKING"
                cv2.putText(frame, status_text, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

                if incident:
                    incidents.append({"frame": frame_id, "strikes": strikes, "penalty": penalty})
                    
        return frame, incidents
