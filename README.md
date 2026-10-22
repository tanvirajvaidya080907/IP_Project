# Vehicle Number Plate Detection & Vehicle Profiling System
### Dual-Mode: Static Image Analysis & Real-Time Live AI Webcam Scanner

An end-to-end Computer Vision and Deep Learning system that operates across two flexible operating modes:
1. **Static Image Upload Mode**: Upload any high-resolution vehicle photo for deep plate localization, OCR candidate generation, and vehicle profiling.
2. **Live AI Webcam Scanner Mode**: Real-time webcam video stream scanning at 30+ FPS with live bounding box HUD overlays, asynchronous OCR, vehicle deduplication, and an auto-updating live identification feed.

---

## 🌟 Dual-Pipeline Architecture

```
[MODE 1: STATIC IMAGE UPLOAD]              [MODE 2: LIVE AI WEBCAM STREAM]
            ↓                                            ↓
   User Uploads Photo                          DirectShow Webcam Stream (30+ FPS)
            ↓                                            ↓
   YOLO Plate Localization                     YOLO Plate Detection (Every 2nd frame)
            ↓                                            ↓
    Plate Crop Extraction                      Temporal Deduplication (8s Cooldown)
            ↓                                            ↓
 8 OpenCV Preprocessing Filters               Background Async OCR Worker Queue
            ↓                                            ↓
   Tesseract Multi-PSM OCR                     Intelligent Database Matcher
            ↓                                            ↓
  Database Profiling Engine                   Real-Time Stream HUD + Live Log Cards
            ↓                                            ↓
Full Vehicle Report Dashboard                  Interactive Stream & CSV Export
```

---

## 📁 Project Structure

```
Vehicle_Number_Plate_System/
│
├── app.py                     # Flask web server (serves both Upload & Live Webcam)
├── video_processor.py         # Real-time threaded live webcam processor & deduplication
├── plate_detection.py         # YOLO inference, green bbox drawing, tight cropping
├── ocr.py                     # OpenCV preprocessing (8 variants) & Tesseract OCR
├── database.py                # Multi-stage database plate matching engine
├── create_database.py         # SQLite database generator with deterministic profiles
├── prepare_yolo_dataset.py    # Pascal VOC XML to YOLO dataset converter (80/10/10 split)
├── train_model.py             # Ultralytics YOLO training script (trained ONLY on video_images)
├── evaluate_model.py          # Model evaluation (Precision, Recall, mAP50, mAP50-95)
├── test_detection.py          # Automated pipeline testing on real dataset images
├── requirements.txt           # Project dependencies
├── README.md                  # Project documentation
│
├── dataset/
│   └── video_images/          # Source video_images and corresponding XML annotations
│
├── yolo_dataset/              # Converted YOLO dataset
│   ├── images/ (train, val, test)
│   ├── labels/ (train, val, test)
│   └── data.yaml
│
├── runs/
│   └── detect/                # YOLO training weights, plots, and metrics
│
├── uploads/                   # Uploaded images, debug visualizations & plate crops
│   └── live_crops/            # Live recognized vehicle license plate crops
│
├── templates/
│   ├── index.html             # Static image upload dashboard (Mode 1)
│   ├── vehicle_identified.html# Detailed vehicle identification report
│   └── live_webcam.html       # Real-time Live AI Webcam HUD dashboard (Mode 2)
│
└── static/
    ├── styles.css             # Glassmorphism, dark navy, cyan accents
    └── vehicle_identified.css # Result report styling
```

---

## 🚀 Setup & Execution

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Tesseract OCR Configuration
Ensure Tesseract OCR is installed on Windows:
- `C:\Program Files\Tesseract-OCR\tesseract.exe`
- Or configured via the `TESSERACT_CMD` environment variable.

### 3. Launch the Application
```bash
python app.py
```
Open your browser and navigate to:
**`http://127.0.0.1:5000`**

### 🔄 Switching Modes in the Web App
Use the navigation tabs at the top of the interface:
* 📷 **Static Image Mode** (`http://127.0.0.1:5000/`) — Drag and drop or browse vehicle images to get a full report.
* 🎥 **Live AI Webcam Feed** (`http://127.0.0.1:5000/live`) — Start your live camera for continuous real-time license plate detection and logging.
