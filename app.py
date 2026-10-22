import os
import time
import uuid
import cv2
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, Response, jsonify

from plate_detection import PlateDetector
from ocr import perform_ocr_on_plate, print_tesseract_status, TESSERACT_AVAILABLE, TESSERACT_PATH
from database import find_best_vehicle_match, normalize_registration
from video_processor import WebcamProcessor

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'live_crops'), exist_ok=True)

# Startup information
print("=" * 50)
print("VEHICLE NUMBER PLATE DETECTION & PROFILING SYSTEM")
print("=" * 50)
print_tesseract_status()

# Initialize detector & live webcam processor
detector = PlateDetector()
webcam_processor = WebcamProcessor(detector, uploads_dir=app.config['UPLOAD_FOLDER'])

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def log_analysis(filename, width, height, detector_model, detections, conf, bbox,
                 raw_ocr, candidates, selected_ocr, norm_plate, best_cand, score, match_status):
    """Prints clean, standardized terminal log for every analyzed vehicle image."""
    log_msg = f"""
==================================================
VEHICLE IMAGE ANALYSIS
==================================================

Image: {filename}
Width: {width}
Height: {height}

---------------- YOLO ----------------

Model: {detector_model}
Detections: {detections}
Confidence: {conf:.4f}
Bounding box: {bbox}

---------------- OCR -----------------

Raw OCR: {raw_ocr}
OCR candidates: {candidates}
Selected OCR: {selected_ocr}

---------------- DATABASE ------------

Normalized plate: {norm_plate}
Best candidate: {best_cand}
Matching score: {score:.4f}
Match: {match_status}

==================================================
"""
    print(log_msg, flush=True)

@app.route('/')
def index():
    """Renders the Static Image Upload & Analysis Dashboard."""
    return render_template('index.html', error_message=None)

@app.route('/live')
def live():
    """Renders the Real-Time Live AI Webcam Dashboard."""
    return render_template('live_webcam.html')


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# =========================================================================
# LIVE WEBCAM STREAM & REST API ENDPOINTS
# =========================================================================

@app.route('/video_feed')
def video_feed():
    """Multipart MJPEG video stream from the webcam processor."""
    return Response(
        webcam_processor.generate_mjpeg(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/api/camera/start', methods=['POST'])
def start_camera():
    """Starts the webcam feed."""
    data = request.get_json(silent=True) or {}
    camera_index = data.get('camera_index', 0)
    success, message = webcam_processor.start_camera(camera_index=camera_index)
    return jsonify({
        "success": success,
        "message": message,
        "status": webcam_processor.get_status()
    })

@app.route('/api/camera/stop', methods=['POST'])
def stop_camera():
    """Stops the webcam feed."""
    success, message = webcam_processor.stop_camera()
    return jsonify({
        "success": success,
        "message": message,
        "status": webcam_processor.get_status()
    })

@app.route('/api/camera/status', methods=['GET'])
def camera_status():
    """Returns current live camera metrics."""
    return jsonify(webcam_processor.get_status())

@app.route('/api/camera/detections', methods=['GET'])
def camera_detections():
    """Returns the stream of detected unique vehicles."""
    detections = webcam_processor.get_detections()
    return jsonify({
        "total": len(detections),
        "detections": detections
    })

@app.route('/api/camera/clear', methods=['POST'])
def camera_clear():
    """Clears the live detection history."""
    webcam_processor.clear_detections()
    return jsonify({
        "success": True,
        "message": "Detection history cleared successfully."
    })

# =========================================================================
# STATIC IMAGE ANALYSIS
# =========================================================================

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'vehicle_image' not in request.files:
        return render_template('index.html', error_message="No image file provided in upload request.")
        
    file = request.files['vehicle_image']
    if file.filename == '':
        return render_template('index.html', error_message="No file selected. Please select an image.")

    if not allowed_file(file.filename):
        return render_template('index.html', error_message="Invalid file format. Allowed formats: .jpg, .jpeg, .png, .webp")

    try:
        # Generate secure unique filename
        ext = file.filename.rsplit('.', 1)[1].lower()
        unique_id = uuid.uuid4().hex[:8]
        saved_filename = f"upload_{unique_id}.{ext}"
        saved_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)
        file.save(saved_path)

        # Step 1: YOLO Plate Detection
        det_result = detector.detect(saved_path)
        img_w, img_h = det_result["image_dims"]

        if not det_result["detected"]:
            log_analysis(
                filename=saved_filename,
                width=img_w,
                height=img_h,
                detector_model=os.path.basename(detector.model_path),
                detections=0,
                conf=0.0,
                bbox=None,
                raw_ocr="N/A",
                candidates=[],
                selected_ocr="N/A",
                norm_plate="N/A",
                best_cand="N/A",
                score=0.0,
                match_status="NO PLATE DETECTED"
            )
            return render_template('index.html', error_message="No number plate detected in uploaded vehicle image. Please try a clearer vehicle photograph.")

        # Save cropped plate image
        crop_filename = f"plate_crop_{unique_id}.jpg"
        crop_path = os.path.join(app.config['UPLOAD_FOLDER'], crop_filename)
        cv2.imwrite(crop_path, det_result["crop"])
        # Also maintain static copy for direct reference
        cv2.imwrite(os.path.join(app.config['UPLOAD_FOLDER'], "plate_crop.jpg"), det_result["crop"])

        # Save unique debug image with GREEN rectangle
        debug_filename = f"detected_plate_debug_{unique_id}.jpg"
        debug_path = os.path.join(app.config['UPLOAD_FOLDER'], debug_filename)
        cv2.imwrite(debug_path, cv2.imread(det_result["debug_image_path"]))

        # Step 2: Multi-variant Tesseract OCR on plate crop
        ocr_result = perform_ocr_on_plate(det_result["crop"])

        # Step 3: Database matching
        candidates = ocr_result["ocr_candidates"]
        db_result = find_best_vehicle_match(candidates)

        resolved_registration = db_result["registration_number"] if db_result["matched"] else (ocr_result["selected_ocr"] or "UNKNOWN")
        norm_plate = normalize_registration(resolved_registration)

        # Standardized Terminal Log
        log_analysis(
            filename=saved_filename,
            width=img_w,
            height=img_h,
            detector_model=os.path.basename(detector.model_path),
            detections=det_result["total_detections"],
            conf=det_result["confidence"],
            bbox=det_result["bbox"],
            raw_ocr=ocr_result.get("raw_ocr", ""),
            candidates=ocr_result.get("ocr_candidates", []),
            selected_ocr=ocr_result.get("selected_ocr", ""),
            norm_plate=norm_plate,
            best_cand=db_result.get("candidate_used", ocr_result.get("selected_ocr", "")),
            score=db_result.get("score", 0.0),
            match_status="MATCHED" if db_result["matched"] else "NOT FOUND IN DATABASE"
        )

        analysis_payload = {
            "registration_number": resolved_registration,
            "confidence": det_result["confidence"],
            "bbox": det_result["bbox"],
            "debug_image_filename": debug_filename,
            "crop_image_filename": crop_filename,
            "ocr": ocr_result,
            "db_match": db_result
        }

        return render_template('vehicle_identified.html', result=analysis_payload, analysis_id=unique_id.upper())

    except Exception as e:
        import traceback
        traceback.print_exc()
        return render_template('index.html', error_message=f"An unexpected error occurred during processing: {str(e)}")

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
