import os
import glob
import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO

class PlateDetector:
    def __init__(self, model_path=None):
        self.model_path = model_path or self._find_best_model()
        print(f"Loading YOLO Plate Detection Model: {self.model_path}")
        self.model = YOLO(self.model_path)

    def _find_best_model(self):
        """Locates the trained best.pt model file dynamically."""
        candidate_paths = [
            os.path.join("runs", "detect", "number_plate_detector", "weights", "best.pt"),
            os.path.join("runs", "detect", "runs", "detect", "number_plate_detector", "weights", "best.pt"),
            os.path.join("runs", "detect", "plate_detection_final", "weights", "best.pt"),
        ]
        for p in candidate_paths:
            if os.path.isfile(p):
                return os.path.abspath(p)
                
        # Search recursively in runs/
        wildcard_matches = glob.glob("runs/**/best.pt", recursive=True)
        if wildcard_matches:
            return os.path.abspath(wildcard_matches[0])
            
        # Fallback to local yolo11n.pt if training is still in progress or not found
        if os.path.isfile("yolo11n.pt"):
            print("Warning: Trained best.pt not found yet. Using yolo11n.pt base model.")
            return os.path.abspath("yolo11n.pt")
            
        raise FileNotFoundError("No YOLO model weights (.pt) found.")

    def reload_model(self):
        """Reloads the model weights if newly trained."""
        self.model_path = self._find_best_model()
        self.model = YOLO(self.model_path)

    def detect(self, image_input, conf_thresh=0.25, enable_multiscale=None, save_debug=True):
        """
        Runs YOLO inference on an image to detect the number plate.
        
        Args:
            image_input: image file path, numpy ndarray, or PIL Image
            conf_thresh: minimum confidence threshold (default 0.25)
            enable_multiscale: optional override for multi-scale padded detection
            save_debug: whether to write uploads/detected_plate_debug.jpg
            
        Returns:
            dict containing:
                - detected: bool
                - bbox: [x1, y1, x2, y2] (integers) or None
                - confidence: float
                - crop: numpy ndarray (BGR) of tightly cropped plate or None
                - debug_image_path: path to saved debug image with GREEN rectangle
                - image_dims: (width, height)
                - total_detections: int
        """
        # Load image into OpenCV BGR format
        if isinstance(image_input, str):
            if not os.path.isfile(image_input):
                raise FileNotFoundError(f"Image not found at {image_input}")
            img_bgr = cv2.imread(image_input)
            if img_bgr is None:
                raise ValueError(f"Could not decode image at {image_input}")
        elif isinstance(image_input, Image.Image):
            img_rgb = np.array(image_input)
            img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        elif isinstance(image_input, np.ndarray):
            img_bgr = image_input.copy()
        else:
            raise TypeError("Unsupported image input type. Provide file path, PIL Image, or numpy array.")

        from ocr import perform_ocr_on_plate, evaluate_plate_structure
        from rto_lookup import parse_indian_registration_format

        h, w = img_bgr.shape[:2]

        def analyze_visuals(cx1, cy1, cx2, cy2):
            bw = max(1, cx2 - cx1)
            bh = max(1, cy2 - cy1)
            ar = bw / float(bh)
            crop = img_bgr[cy1:cy2, cx1:cx2]
            if crop.size == 0 or bw < 25 or bh < 12:
                return None

            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            h_ch, s_ch, v_ch = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
            # Saturated red reflector/taillight mask (excludes amber/yellow H=14-35 & orange bands)
            red_mask = ((h_ch <= 9) | (h_ch >= 167)) & (s_ch >= 90) & (v_ch >= 35)
            red_ratio = float(np.mean(red_mask))

            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            sc = 48.0 / float(max(1, bh))
            interp = cv2.INTER_AREA if sc < 1.0 else cv2.INTER_CUBIC
            g_norm = cv2.resize(gray, (max(8, int(bw * sc)), 48), interpolation=interp)
            sobelx = np.abs(cv2.Sobel(g_norm, cv2.CV_32F, 1, 0, ksize=3))
            edge_density = float(np.mean(sobelx > 40))
            gray_std = float(np.std(g_norm))
            p10, p90 = np.percentile(g_norm, [10, 90])
            dyn_range = float(p90 - p10)

            return {
                "bw": bw,
                "bh": bh,
                "ar": ar,
                "w_frac": bw / float(max(1, w)),
                "h_frac": bh / float(max(1, h)),
                "touches_edge": (cx1 <= 2 or cy1 <= 2 or cx2 >= w - 2 or cy2 >= h - 2),
                "corner_clip": ((cx1 <= 2 and cy1 <= 2) or (cx2 >= w - 2 and cy1 <= 2)),
                "red_ratio": red_ratio,
                "edge_density": edge_density,
                "gray_std": gray_std,
                "dyn_range": dyn_range,
                "crop": crop,
            }

        def is_visually_plausible(vis):
            if vis is None:
                return False
            ar = vis["ar"]
            if ar < 0.65 or ar > 7.8:
                return False
            if vis["red_ratio"] >= 0.40:
                return False
            if vis["red_ratio"] >= 0.25 and vis["edge_density"] < 0.20:
                return False
            if vis["edge_density"] < 0.12 or vis["dyn_range"] < 32.0 or vis["gray_std"] < 10.0:
                return False
            return True

        def collect_yolo_boxes(pad_ratio=0.0):
            if pad_ratio <= 0.0:
                canvas = img_bgr
                ox, oy = 0, 0
            else:
                px, py = int(w * pad_ratio), int(h * pad_ratio)
                canvas = cv2.copyMakeBorder(
                    img_bgr, py, py, px, px, cv2.BORDER_CONSTANT, value=(114, 114, 114)
                )
                ox, oy = px, py

            res = self.model.predict(canvas, conf=conf_thresh, verbose=False)
            found = []
            if len(res) > 0 and res[0].boxes is not None:
                for b in res[0].boxes:
                    coords = b.xyxy[0].cpu().numpy().tolist()
                    conf = float(b.conf[0].cpu().numpy())
                    cls_id = int(b.cls[0].cpu().numpy())
                    rx1 = max(0, min(int(coords[0]) - ox, w - 1))
                    ry1 = max(0, min(int(coords[1]) - oy, h - 1))
                    rx2 = max(rx1 + 1, min(int(coords[2]) - ox, w))
                    ry2 = max(ry1 + 1, min(int(coords[3]) - oy, h))
                    vis = analyze_visuals(rx1, ry1, rx2, ry2)
                    found.append({
                        "coords": [rx1, ry1, rx2, ry2],
                        "confidence": conf,
                        "class_id": cls_id,
                        "pad_ratio": pad_ratio,
                        "vis": vis,
                        "plausible": is_visually_plausible(vis),
                        "ocr": None,
                    })
            return found

        def attach_ocr(cand):
            if cand["ocr"] is not None or cand["vis"] is None:
                return cand["ocr"]
            ocr_res = perform_ocr_on_plate(cand["vis"]["crop"])
            cand["_ocr_full"] = ocr_res
            sel = ocr_res.get("selected_ocr", "") if ocr_res else ""
            cand["ocr"] = {
                "text": sel,
                "struct": evaluate_plate_structure(sel) if sel else 0.0,
                "rto_valid": parse_indian_registration_format(sel) is not None if sel else False,
            }
            return cand["ocr"]

        def box_iou(a, b):
            ax1, ay1, ax2, ay2 = a
            bx1, by1, bx2, by2 = b
            ix1, iy1 = max(ax1, bx1), max(ay1, by1)
            ix2, iy2 = min(ax2, bx2), min(ay2, by2)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            if inter <= 0:
                return 0.0
            area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
            area_b = max(1, (bx2 - bx1) * (by2 - by1))
            return inter / float(area_a + area_b - inter)

        def rank_candidate(cand, use_ocr=True):
            vis = cand["vis"]
            score = cand["confidence"]
            ar = vis["ar"]
            if 1.1 <= ar <= 6.0:
                score += 0.08
            elif ar < 0.95 or ar > 6.8:
                score -= 0.25
            if vis["edge_density"] >= 0.22:
                score += 0.06
            elif vis["edge_density"] < 0.16:
                score -= 0.15
            if vis["corner_clip"]:
                score -= 0.22
            if use_ocr:
                ocr = attach_ocr(cand)
                if ocr is not None:
                    if ocr["rto_valid"] and ocr["struct"] >= 0.95:
                        score += 0.45
                    elif ocr["rto_valid"]:
                        score += 0.25
                    elif ocr["struct"] >= 0.65:
                        score += 0.10
                    elif len(ocr["text"]) <= 5:
                        score -= 0.15
            return score

        raw_native = collect_yolo_boxes(0.0)
        valid_native = [c for c in raw_native if c["plausible"]]

        multiscale_enabled = getattr(self, "enable_multiscale", True) if enable_multiscale is None else bool(enable_multiscale)
        candidate_pool = list(valid_native)

        # Preserve fast path for clear, confident single-scale car/traffic plates
        fast_native_ok = False
        if len(valid_native) >= 1:
            top_nat = max(valid_native, key=lambda c: c["confidence"])
            tv = top_nat["vis"]
            if (
                len(raw_native) == 1
                and top_nat["confidence"] >= 0.75
                and not tv["touches_edge"]
                and tv["w_frac"] <= 0.45
                and tv["h_frac"] <= 0.30
            ):
                fast_native_ok = True
            elif multiscale_enabled and len(valid_native) >= 1 and top_nat["confidence"] >= 0.58 and not tv["touches_edge"]:
                ocr_top = attach_ocr(top_nat)
                if ocr_top is not None and ocr_top["rto_valid"] and ocr_top["struct"] >= 1.05:
                    fast_native_ok = True

        # Escalate to zoomed-out neutral-padded canvas passes when native boxes are missing, partial, or low-conf
        if multiscale_enabled and not fast_native_ok:
            pad1 = [c for c in collect_yolo_boxes(0.38) if c["plausible"]]
            candidate_pool.extend(pad1)

            has_strong_plate = False
            for c in candidate_pool:
                if c["confidence"] >= 0.70:
                    oc = attach_ocr(c)
                    if oc is not None and oc["rto_valid"] and oc["struct"] >= 0.90:
                        has_strong_plate = True
                        break

            if not has_strong_plate:
                pad2 = [c for c in collect_yolo_boxes(0.80) if c["plausible"]]
                candidate_pool.extend(pad2)

            if not candidate_pool:
                pad3 = [c for c in collect_yolo_boxes(1.25) if c["plausible"]]
                candidate_pool.extend(pad3)

        # Deduplicate near-identical boxes across passes, keeping highest YOLO confidence
        deduped_pool = []
        for cand in sorted(candidate_pool, key=lambda c: c["confidence"], reverse=True):
            if not any(box_iou(cand["coords"], k["coords"]) > 0.90 for k in deduped_pool):
                deduped_pool.append(cand)

        def _no_plate_result():
            debug_path = None
            if save_debug:
                os.makedirs("uploads", exist_ok=True)
                debug_path = os.path.join("uploads", "detected_plate_debug.jpg")
                cv2.imwrite(debug_path, img_bgr)
            return {
                "detected": False,
                "bbox": None,
                "confidence": 0.0,
                "crop": None,
                "debug_image_path": debug_path,
                "image_dims": (w, h),
                "total_detections": 0,
                "message": "No plate detected"
            }

        if not deduped_pool:
            return _no_plate_result()

        use_ocr_select = multiscale_enabled and (len(deduped_pool) > 1 or not fast_native_ok)
        best_box = max(deduped_pool, key=lambda c: rank_candidate(c, use_ocr=use_ocr_select))

        # Final negative validation gate: reject isolated corner artifacts, reflectors, or empty frames
        bv = best_box["vis"]
        b_ocr = best_box["ocr"]
        if use_ocr_select and b_ocr is None:
            b_ocr = attach_ocr(best_box)
        rto_ok = bool(b_ocr and b_ocr["rto_valid"])
        struct_val = b_ocr["struct"] if b_ocr else 0.0

        reject_final = False
        if bv["corner_clip"] and not rto_ok and best_box["confidence"] < 0.75:
            reject_final = True
        elif bv["touches_edge"] and not rto_ok and best_box["confidence"] < 0.40:
            reject_final = True
        elif not rto_ok and struct_val < 0.65 and best_box["confidence"] < 0.30:
            reject_final = True
        elif bv["red_ratio"] >= 0.30 and not rto_ok:
            reject_final = True
        elif bv["edge_density"] < 0.11 and best_box["confidence"] < 0.65 and struct_val < 0.80:
            reject_final = True

        if reject_final:
            return _no_plate_result()

        total_detections = len(deduped_pool)
        x1, y1, x2, y2 = best_box["coords"]
        
        # Clamp coordinates to image boundaries
        x1 = max(0, min(x1, w - 1))
        x2 = max(x1 + 1, min(x2, w))
        y1 = max(0, min(y1, h - 1))
        y2 = max(y1 + 1, min(y2, h))

        # Tightly crop the number plate according to actual detected coordinates
        plate_crop = img_bgr[y1:y2, x1:x2].copy()

        debug_path = None
        if save_debug:
            # Draw GREEN bounding box on debug image
            debug_img = img_bgr.copy()
            # Line thickness adaptive to image size
            thickness = max(2, int(min(w, h) / 300))
            cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 0), thickness)
            
            # Draw clean label
            label = f"Plate: {best_box['confidence']:.2f}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = max(0.5, thickness * 0.25)
            text_size = cv2.getTextSize(label, font, font_scale, 1)[0]
            text_x = x1
            text_y = max(text_size[1] + 5, y1 - 8)
            
            # Background rectangle for text
            cv2.rectangle(
                debug_img,
                (text_x, text_y - text_size[1] - 4),
                (text_x + text_size[0] + 6, text_y + 4),
                (0, 255, 0),
                -1
            )
            # Black text on green banner
            cv2.putText(debug_img, label, (text_x + 3, text_y), font, font_scale, (0, 0, 0), 1, cv2.LINE_AA)

            # Save debug image to uploads/detected_plate_debug.jpg
            os.makedirs("uploads", exist_ok=True)
            debug_path = os.path.join("uploads", "detected_plate_debug.jpg")
            cv2.imwrite(debug_path, debug_img)

        return {
            "detected": True,
            "bbox": [x1, y1, x2, y2],
            "confidence": round(best_box["confidence"], 4),
            "crop": plate_crop,
            "ocr_result": best_box.get("_ocr_full"),
            "debug_image_path": debug_path,
            "image_dims": (w, h),
            "total_detections": total_detections,
            "message": "Number plate detected successfully"
        }

if __name__ == "__main__":
    detector = PlateDetector()
    print("PlateDetector initialized successfully.")
