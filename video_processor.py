import os
import time
import uuid
import queue
import threading
import cv2
import numpy as np
from datetime import datetime

from ocr import perform_ocr_on_plate, evaluate_plate_structure
from database import find_best_vehicle_match, normalize_registration
from rto_lookup import resolve_registration_fallback, parse_indian_registration_format

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
        self.lookup_cache = {}    # {cache_key: (timestamp, db_result, fallback_profile)}
        self.plate_cooldown_seconds = 15.0  # Avoid repeated DB lookups/logging within cooldown window
        
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

        while True:
            with self.lock:
                if not self.is_running or self.cap is None:
                    break
                cap = self.cap
            if not cap.isOpened():
                break
            ret, frame = cap.read()
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
            with self.lock:
                self.active_overlays = [ov for ov in self.active_overlays if now - ov['timestamp'] < 2.0]

            # Run YOLO Detection every N frames using same full pipeline as static image uploads
            if frame_idx % process_every_n_frames == 0:
                try:
                    det_result = self.detector.detect(
                        frame,
                        conf_thresh=0.25,
                        enable_multiscale=True,
                        save_debug=False,
                    )
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

    def _cached_lookup(self, selected_ocr, candidates):
        """Runs DB match and read-only RTO fallback with TTL cache to avoid per-frame DB churn."""
        cand_list = [str(c).strip() for c in (candidates or []) if c and str(c).strip()]
        if selected_ocr and selected_ocr not in cand_list:
            cand_list.insert(0, selected_ocr)

        norm_key = "|".join(normalize_registration(c) for c in cand_list[:5]) or normalize_registration(selected_ocr)
        now = time.time()

        if norm_key:
            with self.lock:
                cached = self.lookup_cache.get(norm_key)
                if cached is not None and (now - cached[0]) < self.plate_cooldown_seconds:
                    return cached[1], cached[2]

        db_result = find_best_vehicle_match(cand_list)
        fallback_profile = None
        if not db_result.get("matched"):
            fallback_profile = resolve_registration_fallback(selected_ocr, candidates=cand_list)

        if norm_key:
            with self.lock:
                if len(self.lookup_cache) > 100:
                    cutoff = now - self.plate_cooldown_seconds
                    self.lookup_cache = {k: v for k, v in self.lookup_cache.items() if v[0] >= cutoff}
                self.lookup_cache[norm_key] = (now, db_result, fallback_profile)

        return db_result, fallback_profile

    def _resolve_and_record_plate(self, plate_crop, bbox, conf, ocr_result):
        """Resolves DB/RTO vehicle profile and records detection with cooldown protection."""
        candidates = ocr_result.get("ocr_candidates", [])
        selected_ocr = (ocr_result.get("selected_ocr") or "").strip()

        if not selected_ocr and not candidates:
            return {
                "resolved_plate": "",
                "matched": False,
                "is_fallback": False,
                "ocr_uncertain": True,
                "profile_source": "Detection Uncertain",
                "vehicle_details": None,
            }

        db_result, fallback_profile = self._cached_lookup(selected_ocr, candidates)

        matched = bool(db_result.get("matched") and db_result.get("vehicle_info"))
        is_fallback_valid = bool(fallback_profile and fallback_profile.get("is_valid_format"))

        if matched:
            resolved_plate = db_result["registration_number"]
            v_info = db_result.get("vehicle_info") or {}
            vehicle_details = {
                "fuel_type": v_info.get("fuel_type", "Not Available"),
                "state_name": v_info.get("state_name", "Not Available"),
                "rto_code": v_info.get("rto_code", "Not Available"),
                "registration_date": v_info.get("registration_date", "Not Available"),
                "vehicle_age": v_info.get("vehicle_age", "Not Available"),
            }
            profile_source = "Database Matched"
            ocr_uncertain = False
        elif is_fallback_valid:
            resolved_plate = fallback_profile["registration_number"]
            vehicle_details = {
                "fuel_type": fallback_profile.get("fuel_type", "Not Available"),
                "state_name": fallback_profile.get("state", "Not Available"),
                "rto_code": fallback_profile.get("rto_authority", "Not Available"),
                "registration_date": fallback_profile.get("registration_date", "Not Available"),
                "vehicle_age": fallback_profile.get("vehicle_age", "Not Available"),
            }
            profile_source = "Registration Code Lookup"
            ocr_uncertain = False
        else:
            resolved_plate = selected_ocr or (candidates[0] if candidates else "")
            norm_check = normalize_registration(resolved_plate)
            is_plausible = bool(
                norm_check
                and (parse_indian_registration_format(norm_check) or evaluate_plate_structure(norm_check) >= 0.65)
            )
            ocr_uncertain = not is_plausible
            vehicle_details = {
                "fuel_type": "Not Available",
                "state_name": "Not Available",
                "rto_code": "Not Available",
                "registration_date": "Not Available",
                "vehicle_age": "Not Available",
            }
            profile_source = "OCR Recognized" if is_plausible else "OCR Uncertain"

        norm_plate = normalize_registration(resolved_plate)
        if len(norm_plate) < 4 or ocr_uncertain:
            self._update_overlay(bbox, resolved_plate or "PLATE DETECTED", False, conf)
            return {
                "resolved_plate": resolved_plate,
                "matched": False,
                "is_fallback": False,
                "ocr_uncertain": True,
                "profile_source": "OCR Uncertain",
                "vehicle_details": None,
            }

        now = time.time()
        timestamp_str = datetime.now().strftime("%I:%M:%S %p")
        date_str = datetime.now().strftime("%b %d, %Y")
        conf_pct = round(conf * 100, 1)

        with self.lock:
            existing_idx = None
            for idx, item in enumerate(self.detected_vehicles):
                if item.get("normalized_plate") == norm_plate:
                    existing_idx = idx
                    break

            last_saved = self.tracked_plates.get(norm_plate, 0.0)
            within_cooldown = (now - last_saved) < self.plate_cooldown_seconds

            if existing_idx is not None and within_cooldown:
                # Avoid writing duplicate crops or querying DB repeatedly while plate stays visible
                self.detected_vehicles[existing_idx]["timestamp"] = timestamp_str
                if conf_pct > self.detected_vehicles[existing_idx]["confidence"]:
                    self.detected_vehicles[existing_idx]["confidence"] = conf_pct
                should_write_crop = False
            else:
                should_write_crop = True
                self.tracked_plates[norm_plate] = now

        if should_write_crop:
            crop_id = uuid.uuid4().hex[:8]
            crop_filename = f"live_{norm_plate}_{crop_id}.jpg"
            crop_path = os.path.join(self.live_crops_dir, crop_filename)
            cv2.imwrite(crop_path, plate_crop)

            vehicle_record = {
                "id": crop_id,
                "registration_number": resolved_plate,
                "normalized_plate": norm_plate,
                "matched": matched,
                "is_fallback": is_fallback_valid,
                "profile_source": profile_source,
                "confidence": conf_pct,
                "timestamp": timestamp_str,
                "date": date_str,
                "crop_url": f"/uploads/live_crops/{crop_filename}",
                "vehicle_details": vehicle_details,
                "match_score": db_result.get("score", 1.0 if matched else 0.0),
                "candidate_used": db_result.get("candidate_used", selected_ocr),
            }

            with self.lock:
                # Re-check index inside lock
                existing_idx = next(
                    (i for i, item in enumerate(self.detected_vehicles) if item.get("normalized_plate") == norm_plate),
                    None,
                )
                if existing_idx is not None:
                    self.detected_vehicles[existing_idx] = vehicle_record
                else:
                    self.detected_vehicles.insert(0, vehicle_record)
                    if len(self.detected_vehicles) > 100:
                        self.detected_vehicles.pop()

        self._update_overlay(bbox, resolved_plate, matched, conf)
        tag = "VERIFIED VEHICLE PROFILED" if matched else "LIVE PLATE RECOGNIZED"
        print(f"[{tag}] {resolved_plate} | Conf: {conf_pct}% | Source: {profile_source}", flush=True)

        return {
            "resolved_plate": resolved_plate,
            "matched": matched,
            "is_fallback": is_fallback_valid,
            "ocr_uncertain": False,
            "profile_source": profile_source,
            "vehicle_details": vehicle_details,
        }

    def process_frame(self, frame_bgr):
        """
        Runs the exact shared YOLO detection + OCR + DB/RTO lookup pipeline on a single live webcam frame.
        Used for browser getUserMedia frame submissions without modifying static image upload logic.
        """
        if frame_bgr is None or not isinstance(frame_bgr, np.ndarray) or frame_bgr.size == 0:
            return {
                "detected": False,
                "bbox": None,
                "confidence": 0.0,
                "frame_width": 0,
                "frame_height": 0,
                "registration_number": None,
                "matched": False,
                "is_fallback": False,
                "ocr_uncertain": False,
                "profile_source": None,
                "vehicle_details": None,
                "status_message": "Invalid or empty webcam frame",
                "detections": self.get_detections(),
                "total": len(self.get_detections()),
            }

        h, w = frame_bgr.shape[:2]

        # Skip completely black/uninitialized camera frames
        if float(np.mean(frame_bgr)) < 2.0 and float(np.std(frame_bgr)) < 2.0:
            return {
                "detected": False,
                "bbox": None,
                "confidence": 0.0,
                "frame_width": w,
                "frame_height": h,
                "registration_number": None,
                "matched": False,
                "is_fallback": False,
                "ocr_uncertain": False,
                "profile_source": None,
                "vehicle_details": None,
                "status_message": "Waiting for valid camera frame...",
                "detections": self.get_detections(),
                "total": len(self.get_detections()),
            }

        det_result = self.detector.detect(
            frame_bgr,
            conf_thresh=0.25,
            enable_multiscale=True,
            save_debug=False,
        )

        if not det_result.get("detected") or det_result.get("crop") is None:
            return {
                "detected": False,
                "bbox": None,
                "confidence": 0.0,
                "frame_width": w,
                "frame_height": h,
                "registration_number": None,
                "matched": False,
                "is_fallback": False,
                "ocr_uncertain": False,
                "profile_source": None,
                "vehicle_details": None,
                "status_message": "No plate detected in current frame",
                "detections": self.get_detections(),
                "total": len(self.get_detections()),
            }

        bbox = det_result["bbox"]
        conf = det_result["confidence"]
        ocr_result = det_result.get("ocr_result") or perform_ocr_on_plate(det_result["crop"])
        resolved = self._resolve_and_record_plate(det_result["crop"], bbox, conf, ocr_result)
        all_dets = self.get_detections()

        return {
            "detected": True,
            "bbox": bbox,
            "confidence": conf,
            "frame_width": w,
            "frame_height": h,
            "registration_number": resolved["resolved_plate"] or "PLATE DETECTED",
            "raw_ocr": ocr_result.get("raw_ocr", ""),
            "ocr_candidates": ocr_result.get("ocr_candidates", []),
            "matched": resolved["matched"],
            "is_fallback": resolved["is_fallback"],
            "ocr_uncertain": resolved["ocr_uncertain"],
            "profile_source": resolved["profile_source"],
            "vehicle_details": resolved["vehicle_details"],
            "status_message": (
                "Plate detected — OCR uncertain"
                if resolved["ocr_uncertain"]
                else f"Detected {resolved['resolved_plate']}"
            ),
            "detections": all_dets,
            "total": len(all_dets),
        }

    def _process_plate_ocr_async(self, plate_crop, bbox, conf):
        """Runs OCR and Database lookup asynchronously and updates history."""
        try:
            ocr_result = perform_ocr_on_plate(plate_crop)
            self._resolve_and_record_plate(plate_crop, bbox, conf, ocr_result)
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
        now = time.time()
        with self.lock:
            self.active_overlays = [ov for ov in self.active_overlays if now - ov['timestamp'] < 2.0]
            self.active_overlays.append(overlay_item)

    def _draw_hud(self, img, w, h):
        """Renders futuristic cyber-HUD brackets, scanning reticles, and plate tags."""
        with self.lock:
            overlays = list(self.active_overlays)
            logged_count = len(self.detected_vehicles)

        # 1. Draw Active Plate Overlays
        for ov in overlays:
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
        
        status_text = f"FPS: {self.fps} | Logged: {logged_count}"
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
            self.lookup_cache.clear()
            self.active_overlays.clear()
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
