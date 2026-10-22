import os
import shutil
import re
import cv2
import numpy as np
import pytesseract
from PIL import Image

# Indian State Codes set
INDIAN_STATES = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN",
    "GA", "GJ", "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD",
    "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "PB", "PY", "RJ",
    "SK", "TN", "TR", "TS", "UK", "UP", "WB"
}

# Optical character confusion maps
DIGIT_TO_LETTER = {
    '0': 'O', '1': 'I', '2': 'Z', '5': 'S', '6': 'G', '8': 'B', '7': 'T', '4': 'A'
}

LETTER_TO_DIGIT = {
    'O': '0', 'Q': '0', 'D': '0',
    'I': '1', 'L': '1',
    'Z': '2',
    'S': '5',
    'G': '6', 'C': '0',
    'T': '7',
    'B': '8',
    'A': '4'
}

def detect_tesseract():
    """Detect and configure Tesseract executable on Windows or environment."""
    tess_cmd = os.environ.get("TESSERACT_CMD")
    if tess_cmd and os.path.isfile(tess_cmd):
        pytesseract.pytesseract.tesseract_cmd = tess_cmd
        return True, tess_cmd
        
    which_path = shutil.which("tesseract")
    if which_path and os.path.isfile(which_path):
        pytesseract.pytesseract.tesseract_cmd = which_path
        return True, which_path
        
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        os.path.expanduser(r"~\AppData\Local\Tesseract-OCR\tesseract.exe")
    ]
    for p in candidates:
        if os.path.isfile(p):
            pytesseract.pytesseract.tesseract_cmd = p
            return True, p
            
    return False, "Not Found"

# Initialize Tesseract detection
TESSERACT_AVAILABLE, TESSERACT_PATH = detect_tesseract()

def print_tesseract_status():
    print("=" * 40)
    print("Tesseract Status:")
    print("AVAILABLE" if TESSERACT_AVAILABLE else "NOT AVAILABLE")
    print(f"Path: {TESSERACT_PATH}")
    print("=" * 40)

def clean_ocr_text(raw_text):
    """Clean raw OCR string: uppercase, remove spaces, dashes, punctuation."""
    if not raw_text:
        return ""
    cleaned = re.sub(r'[^A-Za-z0-9]', '', str(raw_text)).upper()
    return cleaned

def generate_preprocessing_variants(crop_bgr):
    """
    Generate multiple OpenCV image preprocessing variants for the plate crop:
    1. Original crop
    2. Grayscale
    3. Upscaled (height min 80-120px)
    4. Contrast enhancement (CLAHE / Gamma)
    5. Sharpening
    6. Bilateral / Gaussian smoothed
    7. Otsu threshold (normal + inverse)
    8. Adaptive threshold
    """
    variants = {}
    if crop_bgr is None or crop_bgr.size == 0:
        return variants
        
    h, w = crop_bgr.shape[:2]
    
    # 1. Original
    variants["original"] = crop_bgr.copy()
    
    # 2. Grayscale
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY) if len(crop_bgr.shape) == 3 else crop_bgr
    variants["gray"] = gray
    
    # 3. Upscaled (resize so height >= 100px)
    scale = max(1.0, 100.0 / float(h)) if h > 0 else 1.0
    new_w, new_h = int(w * scale), int(h * scale)
    upscaled = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    variants["upscaled"] = upscaled
    
    # 4. Contrast enhancement (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(upscaled)
    variants["clahe"] = enhanced
    
    # 5. Sharpening
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    sharpened = cv2.filter2D(enhanced, -1, kernel)
    variants["sharpened"] = sharpened
    
    # 6. Otsu threshold
    blur = cv2.GaussianBlur(enhanced, (5, 5), 0)
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants["otsu"] = otsu
    
    # Inverted Otsu (if text is white on dark background)
    variants["otsu_inv"] = cv2.bitwise_not(otsu)
    
    # 7. Adaptive threshold
    adaptive = cv2.adaptiveThreshold(
        enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 3
    )
    variants["adaptive"] = adaptive
    
    # 8. Morphological closing to join broken characters
    kernel_morph = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    morph = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel_morph)
    variants["morph_otsu"] = morph
    
    return variants

def apply_indian_plate_corrections(text):
    """
    Generates intelligent alternatives for an Indian registration string:
    Typical format: [State: 2 letters][RTO: 1-2 digits][Series: 1-3 letters][Number: 1-4 digits]
    Example: MH43AF5037, DL8CN6308, GJ15CD0564
    """
    if len(text) < 6:
        return [text]
        
    candidates = [text]
    chars = list(text)
    
    # Position 0-1: State code letters
    changed_state = False
    for i in (0, 1):
        if i < len(chars) and chars[i] in DIGIT_TO_LETTER:
            chars[i] = DIGIT_TO_LETTER[chars[i]]
            changed_state = True
            
    # Position 2-3: RTO code digits
    changed_rto = False
    for i in (2, 3):
        if i < len(chars) and chars[i] in LETTER_TO_DIGIT:
            chars[i] = LETTER_TO_DIGIT[chars[i]]
            changed_rto = True
            
    # Trailing 4 characters (or trailing 3-4 chars): Registration number digits
    changed_num = False
    num_start = max(4, len(chars) - 4)
    for i in range(num_start, len(chars)):
        if chars[i] in LETTER_TO_DIGIT:
            chars[i] = LETTER_TO_DIGIT[chars[i]]
            changed_num = True
            
    corrected = "".join(chars)
    if corrected != text:
        candidates.append(corrected)
        
    # Also if state code is known (e.g. starts with MH, DL, etc.), give it high preference
    return candidates

def evaluate_plate_structure(text):
    """Scores how closely text matches the standard Indian plate format."""
    if not text:
        return 0.0
    score = 0.0
    length = len(text)
    
    # Indian plates are usually 8 to 10 characters long
    if 8 <= length <= 10:
        score += 0.35
    elif 6 <= length <= 11:
        score += 0.20
        
    # State code check (first 2 letters)
    if length >= 2:
        st = text[:2]
        if st in INDIAN_STATES:
            score += 0.35
        elif st.isalpha():
            score += 0.15
            
    # RTO digits (chars 2-3 or 2)
    if length >= 4:
        rto = text[2:4]
        if rto.isdigit():
            score += 0.15
            
    # Trailing digits (last 3-4 chars)
    if length >= 6:
        tail = text[-4:]
        if tail.isdigit():
            score += 0.15
        elif any(c.isdigit() for c in tail):
            score += 0.05
            
    return min(1.0, score)

def perform_ocr_on_plate(plate_crop_bgr):
    """
    Executes multi-variant, multi-PSM OCR on the detected plate crop.
    Returns:
        dict containing:
        - raw_ocr: most frequent raw text
        - ocr_candidates: ranked list of candidate strings
        - selected_ocr: top ranked OCR candidate
        - confidence: estimated confidence score
        - variants_used: number of preprocessing variations attempted
    """
    if not TESSERACT_AVAILABLE:
        return {
            "raw_ocr": "",
            "ocr_candidates": [],
            "selected_ocr": "",
            "confidence": 0.0,
            "error": "Tesseract OCR not installed or available on this system."
        }
        
    if plate_crop_bgr is None or plate_crop_bgr.size == 0:
        return {
            "raw_ocr": "",
            "ocr_candidates": [],
            "selected_ocr": "",
            "confidence": 0.0,
            "error": "Empty plate crop provided"
        }

    variants = generate_preprocessing_variants(plate_crop_bgr)
    psm_modes = [7, 8, 6, 13]  # single line, single word, block, raw line
    whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    
    candidate_scores = {}
    candidate_counts = {}
    raw_texts = []
    
    for v_name, img_var in variants.items():
        for psm in psm_modes:
            config = f"--oem 3 --psm {psm} -c tessedit_char_whitelist={whitelist}"
            try:
                # Run OCR
                raw = pytesseract.image_to_string(img_var, config=config)
                clean = clean_ocr_text(raw)
                if not clean:
                    continue
                    
                raw_texts.append(clean)
                
                # Generate confusion variations for Indian format
                possibilities = apply_indian_plate_corrections(clean)
                
                for cand in possibilities:
                    candidate_counts[cand] = candidate_counts.get(cand, 0) + 1
                    
                    # Compute structural score
                    struct_score = evaluate_plate_structure(cand)
                    # Voting bonus
                    vote_score = min(0.30, candidate_counts[cand] * 0.05)
                    total_s = struct_score + vote_score
                    
                    if cand not in candidate_scores or total_s > candidate_scores[cand]:
                        candidate_scores[cand] = total_s
            except Exception:
                continue

    if not candidate_scores:
        return {
            "raw_ocr": "",
            "ocr_candidates": [],
            "selected_ocr": "",
            "confidence": 0.0,
            "error": "No alphanumeric characters recognized by OCR."
        }

    # Rank candidates by total score
    ranked = sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)
    ocr_candidates = [item[0] for item in ranked]
    best_candidate = ocr_candidates[0]
    best_score = round(min(1.0, ranked[0][1]), 4)
    raw_primary = raw_texts[0] if raw_texts else best_candidate

    return {
        "raw_ocr": raw_primary,
        "ocr_candidates": ocr_candidates[:10],
        "selected_ocr": best_candidate,
        "confidence": best_score,
        "variants_count": len(variants)
    }

if __name__ == "__main__":
    print_tesseract_status()
