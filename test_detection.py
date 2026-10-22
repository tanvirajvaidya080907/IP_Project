import os
import glob
import cv2
import numpy as np
from plate_detection import PlateDetector
from ocr import perform_ocr_on_plate
from database import find_best_vehicle_match, normalize_registration

def run_tests():
    print("=" * 60)
    print("    COMPREHENSIVE NUMBER PLATE DETECTION & PROFILING TEST")
    print("=" * 60)
    
    detector = PlateDetector()
    out_dir = os.path.join("runs", "test_outputs")
    os.makedirs(out_dir, exist_ok=True)
    
    # Select representative test images from dataset/video_images
    dataset_dir = "dataset/video_images"
    sample_images = [
        # (category, filename)
        ("Clear plate 1", "car-wbs-MH43AF5037_00000.png"),
        ("Clear plate 2", "car-wbs-MH01DE2780_00000.png"),
        ("Different plate 3", "car-wbs-MH12FU1014_00000.png"),
        ("Large plate", "car-ybs-MH47N4570_00000.png"),
        ("Video frame 1", "video10_1060.jpg"),
        ("Video frame 2", "video10_1070.jpg"),
        ("Small / distance plate", "video10_1080.jpg"),
        ("Different position", "video10_1100.jpg")
    ]
    
    # Filter only files that exist
    valid_test_items = []
    for cat, fname in sample_images:
        fpath = os.path.join(dataset_dir, fname)
        if os.path.exists(fpath):
            valid_test_items.append((cat, fpath))
            
    # Also find additional video images if any listed above aren't present
    if len(valid_test_items) < 6:
        all_imgs = sorted(glob.glob(os.path.join(dataset_dir, "video*.jpg")))
        for p in all_imgs[:6]:
            if p not in [x[1] for x in valid_test_items]:
                valid_test_items.append((f"Video frame ({os.path.basename(p)})", p))

    # Add a synthetic "No valid plate" image (blank nature/pattern)
    blank_img_path = os.path.join(out_dir, "test_no_plate.jpg")
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.circle(blank, (320, 240), 100, (80, 80, 80), -1)
    cv2.putText(blank, "NO VEHICLE HERE", (180, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
    cv2.imwrite(blank_img_path, blank)
    valid_test_items.append(("No plate negative test", blank_img_path))

    results = []
    
    for idx, (cat, img_path) in enumerate(valid_test_items, 1):
        print("\n" + "-" * 50)
        print(f"TEST {idx}: [{cat}] -> {os.path.basename(img_path)}")
        print("-" * 50)
        
        # 1. Detection
        det = detector.detect(img_path)
        w, h = det["image_dims"]
        print(f"Image Dimensions: {w}x{h}")
        print(f"Plate Detected  : {det['detected']}")
        
        if not det["detected"]:
            print("Status          : Safely handled - No plate detected.")
            results.append({
                "category": cat,
                "file": os.path.basename(img_path),
                "detected": False,
                "ocr": "N/A",
                "matched": False,
                "reg": "N/A"
            })
            continue
            
        print(f"YOLO Confidence : {det['confidence']:.4f}")
        print(f"Bounding Box    : {det['bbox']} (surrounded by GREEN rectangle)")
        
        # Save output image
        out_name = f"test_{idx}_{os.path.basename(img_path)}"
        out_dest = os.path.join(out_dir, out_name)
        debug_img = cv2.imread(det["debug_image_path"])
        cv2.imwrite(out_dest, debug_img)
        print(f"Green Box Image : {out_dest}")
        
        # 2. OCR on plate crop
        ocr = perform_ocr_on_plate(det["crop"])
        print(f"Raw OCR         : {ocr.get('raw_ocr', '')}")
        print(f"Selected OCR    : {ocr.get('selected_ocr', '')}")
        print(f"Top Candidates  : {ocr.get('ocr_candidates', [])[:5]}")
        
        # 3. Database Matching
        match = find_best_vehicle_match(ocr.get("ocr_candidates", []))
        print(f"Database Match  : {'MATCHED' if match['matched'] else 'NOT FOUND'}")
        print(f"Identified Reg  : {match['registration_number']}")
        print(f"Matching Score  : {match['score']:.2%}")
        if match["matched"] and match["vehicle_info"]:
            v = match["vehicle_info"]
            print(f"Vehicle Profile : {v['manufacturer']} {v['model']} ({v['manufacturing_year']}) - {v['state_name']}")
            
        results.append({
            "category": cat,
            "file": os.path.basename(img_path),
            "detected": True,
            "confidence": det["confidence"],
            "bbox": det["bbox"],
            "ocr": ocr.get("selected_ocr", ""),
            "matched": match["matched"],
            "reg": match["registration_number"],
            "score": match["score"]
        })

    print("\n" + "=" * 60)
    print("                 TEST SUMMARY REPORT")
    print("=" * 60)
    print(f"{'Category':<25} | {'Detected':<8} | {'Reg / OCR':<14} | {'Match':<8} | {'Score'}")
    print("-" * 65)
    for r in results:
        det_str = "YES" if r.get("detected") else "NO"
        reg_str = str(r.get("reg", "N/A"))[:14]
        m_str = "MATCH" if r.get("matched") else "NO MATCH"
        s_str = f"{r.get('score', 0):.2%}" if "score" in r else "N/A"
        print(f"{r['category']:<25} | {det_str:<8} | {reg_str:<14} | {m_str:<8} | {s_str}")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
