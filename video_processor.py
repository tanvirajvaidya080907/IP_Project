import os
import time
import uuid
import queue
import threading
import cv2
import numpy as np
from datetime import datetime

from ocr import perform_ocr_on_plate
from database import find_best_vehicle_match, normalize_registration

class WebcamProcessor:
    def __init__(self, detector, uploads_dir="uploads"):
        self.detector = detector
        self.uploads_dir = uploads_dir
        self.live_crops_dir = os.path.join(self.uploads_dir, "live_crops")
        os.makedirs(self.live_crops_dir, exist_ok=True)

        self.cap = None
        self.camera_index = 0
        self.is_running = False
        
        self.lock = threading.Lock()
        self.current_frame = None
        self.processed_frame = None
        
        # Performance & Tracking Metrics
        self.fps = 0.0
        self.frame_count = 0
        self.last_fps_time = time.time()
        
        # Vehicle Detections History & Tracking
        self.detected_vehicles = []
        self.tracked_plates = {}  # {plate_str: last_seen_timestamp}
        self.plate_cooldown_seconds = 8.0  # Avoid logging same plate repeatedly within 8s
        
        # Async OCR Worker Queue
        self.ocr_queue = queue.Queue(maxsize=10)
        self.ocr_busy = False
        
        # Active detections overlay for video rendering
        self.active_overlays = []  # [{bbox, label, matched, timestamp}]
        
        # Threads
        self.capture_thread = None
        self.ocr_thread = None
        
        # Start background OCR worker
        self._start_ocr_worker()

    def _start_ocr_worker(self):
        """Starts asynchronous OCR worker to avoid freezing the video stream."""
        def worker():
            while True:
                task = self.ocr_queue.get()
                if task is None:
                    break
                try:
                    crop_img, bbox, conf = task
                    self._process_plate_ocr_async(crop_img, bbox, conf)
                except Exception as e:
                    print(f"[Live OCR Worker Error] {e}", flush=True)
                finally:
                    self.ocr_queue.task_done()

        self.ocr_thread = threading.Thread(target=worker, daemon=True)
        self.ocr_thread.start()

    def start_camera(self, camera_index=0):
        """Starts the webcam capture loop in a background thread."""
        with self.lock:
            if self.is_running:
                return True, "Camera is already running."
            
            self.camera_index = int(camera_index)
            
            # On Windows, try DirectShow first for fast startup, fallback to default backend
            if os.name == 'nt':
                self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(self.camera_index)
            else:
                self.cap = cv2.VideoCapture(self.camera_index)
                
            if not self.cap.isOpened():
                self.cap = None
                return False, f"Could not access webcam at index {self.camera_index}."

            # Set resolution for balance of speed and clarity
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            self.is_running = True
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()
            
            print(f"[WebcamProcessor] Camera started on index {self.camera_index}", flush=True)
            return True, "Camera started successfully."

    def stop_camera(self):
        """Stops the webcam capture loop and releases the camera."""
        with self.lock:
            if not self.is_running:
                return True, "Camera is already stopped."
            
            self.is_running = False
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            
            self.active_overlays = []
            print("[WebcamProcessor] Camera stopped.", flush=True)
            return True, "Camera stopped successfully."

    def _capture_loop(self):
        """Continuous frame reading and processing loop."""
        fps_counter = 0
        fps_timer = time.time()
        process_every_n_frames = 2  # Run YOLO on every 2nd frame for smooth 30+ FPS
        frame_idx = 0

        while self.is_running and self.cap is not None and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            frame_idx += 1
            h, w = frame.shape[:2]

            # Calculate live FPS
            fps_counter += 1
            if time.time() - fps_timer >= 1.0:
                self.fps = round(fps_counter / (time.time() - fps_timer), 1)
                fps_counter = 0
                fps_timer = time.time()

            # Clean expired overlays (older than 2 seconds)
            now = time.time()
            self.active_overlays = [ov for ov in self.active_overlays if now - ov['timestamp'] < 2.0]

            # Run YOLO Detection every N frames
            if frame_idx % process_every_n_frames == 0:
                try:
                    det_result = self.detector.detect(frame, conf_thresh=0.35)
                    if det_result["detected"] and det_result["crop"] is not None:
                        bbox = det_result["bbox"]
                        conf = det_result["confidence"]
                        
                        # Queue for asynchronous OCR if queue isn't flooded
                        if self.ocr_queue.qsize() < 2:
                            self.ocr_queue.put((det_result["crop"].copy(), bbox, conf))
                except Exception as e:
                    print(f"[Live YOLO Detection Error] {e}", flush=True)

            # Annotate current frame with HUD overlays
            annotated_frame = self._draw_hud(frame.copy(), w, h)

            with self.lock:
                self.processed_frame = annotated_frame
                self.current_frame = frame

            time.sleep(0.005)

    def _process_plate_ocr_async(self, plate_crop, bbox, conf):
        """Runs OCR and Database lookup asynchronously and updates history."""
        try:
            ocr_result = perform_ocr_on_plate(plate_crop)
            candidates = ocr_result.get("ocr_candidates", [])
            selected_ocr = ocr_result.get("selected_ocr", "").strip()

            if not selected_ocr and not candidates:
                return

            db_result = find_best_vehicle_match(candidates if candidates else [selected_ocr])
            
            resolved_plate = db_result["registration_number"] if db_result["matched"] else (selected_ocr or "UNKNOWN")
            norm_plate = normalize_registration(resolved_plate)

            if len(norm_plate) < 4:
                return  # Filter out short noise strings

            # STRICT REQUIREMENT: Only keep verified database matches
            if not db_result["matched"] or not db_result.get("vehicle_info"):
                # Update HUD overlay with plate reading, but do not clutter detection feed
                self._update_overlay(bbox, resolved_plate, False, conf)
                return

            v_info = db_result.get("vehicle_info") or {}
            
            # Format display info from database
            manufacturer = v_info.get("manufacturer", "")
            model_name = v_info.get("model", "")
            full_vehicle_name = f"{manufacturer} {model_name}".strip() or "Vehicle Identified"
            v_class = v_info.get("vehicle_class", "Car")
            fuel = v_info.get("fuel_type", "Petrol")
            state_name = v_info.get("state_name", "")
            rto = v_info.get("rto_code", "")
            reg_date = v_info.get("registration_date", "")
            mfg_year = v_info.get("manufacturing_year", "")

            # Save plate crop image
            crop_id = uuid.uuid4().hex[:8]
            crop_filename = f"live_{norm_plate}_{crop_id}.jpg"
            crop_path = os.path.join(self.live_crops_dir, crop_filename)
            cv2.imwrite(crop_path, plate_crop)

            timestamp_str = datetime.now().strftime("%I:%M:%S %p")
            date_str = datetime.now().strftime("%b %d, %Y")

            vehicle_record = {
                "id": crop_id,
                "registration_number": resolved_plate,
                "normalized_plate": norm_plate,
                "matched": True,
                "confidence": round(conf * 100, 1),
                "timestamp": timestamp_str,
                "date": date_str,
                "crop_url": f"/uploads/live_crops/{crop_filename}",
                "vehicle_details": {
                    "vehicle_make": manufacturer,
                    "vehicle_model": model_name,
                    "full_name": full_vehicle_name,
                    "vehicle_class": v_class,
                    "fuel_type": fuel,
                    "state_name": state_name,
                    "rto_code": rto,
                    "registration_date": reg_date,
                    "manufacturing_year": mfg_year
                },
                "match_score": db_result.get("score", 1.0),
                "candidate_used": db_result.get("candidate_used", selected_ocr)
            }

            with self.lock:
                # Deduplicate: If this plate is already in the list, update it in place
                existing_idx = None
                for idx, item in enumerate(self.detected_vehicles):
                    if item.get("normalized_plate") == norm_plate:
                        existing_idx = idx
                        break

                if existing_idx is not None:
                    # Update existing record with higher confidence / latest timestamp
                    if conf * 100 >= self.detected_vehicles[existing_idx]["confidence"]:
                        self.detected_vehicles[existing_idx] = vehicle_record
                    else:
                        self.detected_vehicles[existing_idx]["timestamp"] = timestamp_str
                else:
                    # Add new verified vehicle at the top
                    self.detected_vehicles.insert(0, vehicle_record)
                    if len(self.detected_vehicles) > 100:
                        self.detected_vehicles.pop()

            # Update active HUD overlay
            self._update_overlay(bbox, resolved_plate, True, conf)
            print(f"[VERIFIED VEHICLE PROFILED] {resolved_plate} → {full_vehicle_name} ({v_class}) | Score: {db_result.get('score', 1.0)}", flush=True)

        except Exception as e:
            print(f"[Error in _process_plate_ocr_async] {e}", flush=True)

    def _update_overlay(self, bbox, plate_text, matched, conf):
        """Updates or adds active bounding box HUD overlay."""
        overlay_item = {
            "bbox": bbox,
            "label": f"{plate_text} ({int(conf * 100)}%)",
            "matched": matched,
            "timestamp": time.time()
        }
        # Replace or append
        self.active_overlays = [ov for ov in self.active_overlays if time.time() - ov['timestamp'] < 2.0]
        self.active_overlays.append(overlay_item)

    def _draw_hud(self, img, w, h):
        """Renders futuristic cyber-HUD brackets, scanning reticles, and plate tags."""
        # 1. Draw Active Plate Overlays
        for ov in self.active_overlays:
            x1, y1, x2, y2 = ov["bbox"]
            is_matched = ov["matched"]
            box_color = (0, 255, 0) if is_matched else (0, 215, 255)  # Green if in DB, Yellow/Cyan if unknown
            
            # Corner HUD brackets
            line_len = max(12, int((x2 - x1) * 0.2))
            thick = 2
            
            # Top-left
            cv2.line(img, (x1, y1), (x1 + line_len, y1), box_color, thick)
            cv2.line(img, (x1, y1), (x1, y1 + line_len), box_color, thick)
            # Top-right
            cv2.line(img, (x2, y1), (x2 - line_len, y1), box_color, thick)
            cv2.line(img, (x2, y1), (x2, y1 + line_len), box_color, thick)
            # Bottom-left
            cv2.line(img, (x1, y2), (x1 + line_len, y2), box_color, thick)
            cv2.line(img, (x1, y2), (x1, y2 - line_len), box_color, thick)
            # Bottom-right
            cv2.line(img, (x2, y2), (x2 - line_len, y2), box_color, thick)
            cv2.line(img, (x2, y2), (x2, y2 - line_len), box_color, thick)
            
            # Light bounding box outline
            cv2.rectangle(img, (x1, y1), (x2, y2), box_color, 1)

            # Label banner
            label = ov["label"]
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.55
            text_size = cv2.getTextSize(label, font, font_scale, 1)[0]
            
            label_y = max(y1 - 8, text_size[1] + 10)
            cv2.rectangle(img, (x1, label_y - text_size[1] - 6), (x1 + text_size[0] + 10, label_y + 4), box_color, -1)
            cv2.putText(img, label, (x1 + 5, label_y - 2), font, font_scale, (0, 0, 0), 1, cv2.LINE_AA)

        # 2. Live HUD Header Banner
        cv2.rectangle(img, (15, 15), (270, 75), (10, 18, 30), -1)
        cv2.rectangle(img, (15, 15), (270, 75), (0, 215, 255), 1)
        
        # Red pulsating Live Dot
        dot_color = (0, 0, 255) if int(time.time() * 2) % 2 == 0 else (0, 50, 180)
        cv2.circle(img, (35, 36), 6, dot_color, -1)
        
        cv2.putText(img, "LIVE SCANNER", (50, 41), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        
        status_text = f"FPS: {self.fps} | Logged: {len(self.detected_vehicles)}"
        cv2.putText(img, status_text, (30, 63), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 215, 255), 1, cv2.LINE_AA)

        return img

    def _create_placeholder_frame(self, message="CAMERA OFFLINE"):
        """Generates a high-tech dark placeholder graphic when camera is idle."""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (15, 10, 7)  # Dark navy background
        
        # Tech grid lines
        for x in range(0, 640, 40):
            cv2.line(img, (x, 0), (x, 480), (30, 20, 15), 1)
        for y in range(0, 480, 40):
            cv2.line(img, (0, y), (640, y), (30, 20, 15), 1)

        # Center reticle
        cv2.circle(img, (320, 240), 60, (0, 215, 255), 1)
        cv2.circle(img, (320, 240), 4, (0, 215, 255), -1)
        cv2.line(img, (320, 160), (320, 320), (0, 215, 255), 1)
        cv2.line(img, (240, 240), (400, 240), (0, 215, 255), 1)

        # Message text
        font = cv2.FONT_HERSHEY_SIMPLEX
        text_size = cv2.getTextSize(message, font, 0.75, 2)[0]
        text_x = (640 - text_size[0]) // 2
        cv2.putText(img, message, (text_x, 340), font, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
        
        subtext = "Click 'Start Live Webcam' to initialize AI vision feed"
        sub_size = cv2.getTextSize(subtext, font, 0.45, 1)[0]
        sub_x = (640 - sub_size[0]) // 2
        cv2.putText(img, subtext, (sub_x, 370), font, 0.45, (140, 160, 180), 1, cv2.LINE_AA)
        
        return img

    def generate_mjpeg(self):
        """Yields MJPEG stream byte chunks for Flask streaming response."""
        while True:
            frame_to_send = None
            with self.lock:
                if self.is_running and self.processed_frame is not None:
                    frame_to_send = self.processed_frame.copy()
            
            if frame_to_send is None:
                frame_to_send = self._create_placeholder_frame("CAMERA OFFLINE")

            ret, buffer = cv2.imencode('.jpg', frame_to_send, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ret:
                time.sleep(0.03)
                continue

            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.033)  # ~30 FPS stream cap

    def get_detections(self):
        """Returns the logged vehicle detections."""
        with self.lock:
            return list(self.detected_vehicles)

    def clear_detections(self):
        """Clears logged detections."""
        with self.lock:
            self.detected_vehicles.clear()
            self.tracked_plates.clear()
            return True

    def get_status(self):
        """Returns current status summary."""
        with self.lock:
            return {
                "is_running": self.is_running,
                "camera_index": self.camera_index,
                "fps": self.fps,
                "total_logged": len(self.detected_vehicles)
            }
