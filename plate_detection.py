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

    def detect(self, image_input, conf_thresh=0.25):
        """
        Runs YOLO inference on an image to detect the number plate.
        
        Args:
            image_input: image file path, numpy ndarray, or PIL Image
            conf_thresh: minimum confidence threshold (default 0.25)
            
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

        h, w = img_bgr.shape[:2]
        
        # Run YOLO inference
        results = self.model.predict(img_bgr, conf=conf_thresh, verbose=False)
        
        boxes = []
        if len(results) > 0 and results[0].boxes is not None:
            for b in results[0].boxes:
                coords = b.xyxy[0].cpu().numpy().tolist()
                conf = float(b.conf[0].cpu().numpy())
                cls_id = int(b.cls[0].cpu().numpy())
                boxes.append({
                    "coords": [int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])],
                    "confidence": conf,
                    "class_id": cls_id
                })

        total_detections = len(boxes)
        
        if total_detections == 0:
            # Safe fallback if no plate is detected
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

        # Select best detection based on confidence and rectangular aspect ratio
        def score_candidate(box_dict):
            x1, y1, x2, y2 = box_dict["coords"]
            bw = max(1, x2 - x1)
            bh = max(1, y2 - y1)
            ar = bw / float(bh)
            # Aspect ratio for number plates is typically between 1.2 and 6.0
            ar_penalty = 1.0
            if ar < 1.0 or ar > 7.0:
                ar_penalty = 0.5
            return box_dict["confidence"] * ar_penalty

        best_box = max(boxes, key=score_candidate)
        x1, y1, x2, y2 = best_box["coords"]
        
        # Clamp coordinates to image boundaries
        x1 = max(0, min(x1, w - 1))
        x2 = max(x1 + 1, min(x2, w))
        y1 = max(0, min(y1, h - 1))
        y2 = max(y1 + 1, min(y2, h))

        # Tightly crop the number plate without aggressive expansion
        plate_crop = img_bgr[y1:y2, x1:x2].copy()

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
            "debug_image_path": debug_path,
            "image_dims": (w, h),
            "total_detections": total_detections,
            "message": "Number plate detected successfully"
        }

if __name__ == "__main__":
    detector = PlateDetector()
    print("PlateDetector initialized successfully.")
