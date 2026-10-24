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

# Known Major RTO prefixes for enhanced validation
KNOWN_RTOS = {
    "MH01", "MH02", "MH03", "MH04", "MH05", "MH12", "MH14", "MH20",
    "MH43", "MH46", "MH47", "MH48", "DL01", "DL03", "DL08", "DL3C",
    "DL8C", "GJ12", "GJ15"
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
    """Clean raw OCR string: uppercase, remove non-alphanumeric characters."""
    if not raw_text:
        return ""
    cleaned = re.sub(r'[^A-Za-z0-9]', '', str(raw_text)).upper()
    return cleaned

def generate_preprocessing_variants(crop_bgr):
    """
    Generate clean OpenCV image preprocessing variants for the plate crop:
    1. Original BGR crop
    2. Grayscale
    3. Upscaled (height scaled with cubic interpolation)
    4. Bilateral filter (denoised without ringing or character destruction)
    5. Contrast enhancement (CLAHE)
    6. Adaptive Gaussian threshold
    7. Otsu binary threshold
    8. Min-Max contrast normalized
    """
    variants = {}
    if crop_bgr is None or crop_bgr.size == 0:
        return variants
        
    h, w = crop_bgr.shape[:2]
    
    # 1. Original BGR
    variants["original"] = crop_bgr.copy()
    
    # 2. Grayscale
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY) if len(crop_bgr.shape) == 3 else crop_bgr.copy()
    variants["gray"] = gray
    
    # 3. Upscaled
    scale = max(1.5, 90.0 / float(h)) if h > 0 else 1.5
    new_w, new_h = int(w * scale), int(h * scale)
    upscaled = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    variants["upscaled"] = upscaled
    
    # 4. Bilateral filter (edge-preserving smoothing)
    bilateral = cv2.bilateralFilter(upscaled, 9, 75, 75)
    variants["bilateral"] = bilateral
    
    # 5. Contrast enhancement (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(upscaled)
    variants["clahe"] = enhanced
    
    # 6. Adaptive Gaussian threshold
    adaptive = cv2.adaptiveThreshold(
        bilateral, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 19, 5
    )
    variants["adaptive"] = adaptive
    
    # 7. Otsu threshold
    blur = cv2.GaussianBlur(enhanced, (5, 5), 0)
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants["otsu"] = otsu
    
    # 8. Normalized contrast
    norm_img = cv2.normalize(gray, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX)
    variants["normalized"] = norm_img
    
    return variants

def apply_indian_plate_corrections(text):
    """
    Generates intelligent alternatives for an Indian registration string:
    Typical format: [State: 2 letters][RTO: 1-2 digits][Series: 1-2 letters][Number: 1-4 digits]
    Examples: MH43AF5037, DL8CN6308, MH12FU1014
    """
    if not text or len(text) < 5:
        return [text] if text else []
        
    candidates = {text}
    
    # State prefix optical confusions (e.g. W<->M, K<->M)
    if text.startswith("WH") or text.startswith("KH") or text.startswith("IH"):
        candidates.add("MH" + text[2:])
        
    # Standard 10-character plate: [State 2][RTO 2][Series 2][Number 4]
    if len(text) == 10:
        c = list(text)
        # Pos 0-1: State letters
        for i in (0, 1):
            if c[i] in DIGIT_TO_LETTER:
                c[i] = DIGIT_TO_LETTER[c[i]]
        # Pos 2-3: RTO digits
        for i in (2, 3):
            if c[i] in LETTER_TO_DIGIT:
                c[i] = LETTER_TO_DIGIT[c[i]]
        # Pos 4-5: Series letters
        for i in (4, 5):
            if c[i] in DIGIT_TO_LETTER:
                c[i] = DIGIT_TO_LETTER[c[i]]
        # Pos 6-9: Number digits
        for i in range(6, 10):
            if c[i] in LETTER_TO_DIGIT:
                c[i] = LETTER_TO_DIGIT[c[i]]
        candidates.add("".join(c))
        
    # 9-character plate:
    elif len(text) == 9:
        # Format A: [State 2][RTO 2][Series 1][Number 4] (e.g. MH12F1014)
        c1 = list(text)
        for i in (0, 1):
            if c1[i] in DIGIT_TO_LETTER: c1[i] = DIGIT_TO_LETTER[c1[i]]
        for i in (2, 3):
            if c1[i] in LETTER_TO_DIGIT: c1[i] = LETTER_TO_DIGIT[c1[i]]
        if c1[4] in DIGIT_TO_LETTER: c1[4] = DIGIT_TO_LETTER[c1[4]]
        for i in range(5, 9):
            if c1[i] in LETTER_TO_DIGIT: c1[i] = LETTER_TO_DIGIT[c1[i]]
        candidates.add("".join(c1))
        
        # Format B: [State 2][RTO 1][Series 2][Number 4] (e.g. DL8CN6308)
        c2 = list(text)
        for i in (0, 1):
            if c2[i] in DIGIT_TO_LETTER: c2[i] = DIGIT_TO_LETTER[c2[i]]
        if c2[2] in LETTER_TO_DIGIT: c2[2] = LETTER_TO_DIGIT[c2[2]]
        for i in (3, 4):
            if c2[i] in DIGIT_TO_LETTER: c2[i] = DIGIT_TO_LETTER[c2[i]]
        for i in range(5, 9):
            if c2[i] in LETTER_TO_DIGIT: c2[i] = LETTER_TO_DIGIT[c2[i]]
        candidates.add("".join(c2))
        
        # Format C: Missing initial state letter (e.g. 'M43AFS037' -> 'MH43AF5037')
        if text[0] == 'M' and text[1:3].isdigit():
            c3 = 'MH' + text[1:]
            candidates.update(apply_indian_plate_corrections(c3))
        elif text[0] == 'D' and text[1].isdigit():
            c3 = 'DL' + text[1:]
            candidates.update(apply_indian_plate_corrections(c3))
        elif text[0] == 'G' and text[1:3].isdigit():
            c3 = 'GJ' + text[1:]
            candidates.update(apply_indian_plate_corrections(c3))

    # General trailing 4 digits correction
    if len(text) >= 6:
        c = list(text)
        num_start = max(4, len(c) - 4)
        for i in range(num_start, len(c)):
            if c[i] in LETTER_TO_DIGIT:
                c[i] = LETTER_TO_DIGIT[c[i]]
        candidates.add("".join(c))
        
    # Second pass for state prefix on all generated candidates
    extra = set()
    for cand in candidates:
        if cand.startswith("WH") or cand.startswith("KH") or cand.startswith("IH"):
            extra.add("MH" + cand[2:])
    candidates.update(extra)
    
    return list(candidates)

def evaluate_plate_structure(text):
    """Scores how closely text matches the standard Indian plate format."""
    if not text:
        return 0.0
    text = text.upper()
    score = 0.0
    length = len(text)
    
    # 1. Structural Regex Matching
    if re.match(r'^[A-Z]{2}[0-9]{2}[A-Z]{2}[0-9]{4}$', text):
        score += 0.50  # Perfect standard 10-char plate (e.g. MH43AF5037)
    elif re.match(r'^[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{4}$', text):
        score += 0.40  # Valid 9-char plate (e.g. DL8CN6308, MH12F1014)
    elif re.match(r'^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{1,4}$', text):
        score += 0.25
    elif 8 <= length <= 10:
        score += 0.15
        
    # 2. State Code validation (first 2 letters)
    st = text[:2]
    if st in INDIAN_STATES:
        score += 0.30
    elif st.isalpha():
        score += 0.10
        
    # 3. RTO Code validation
    rto4 = text[:4]
    if rto4 in KNOWN_RTOS:
        score += 0.20
    elif len(text) >= 4 and text[2:4].isdigit():
        score += 0.10
        
    # 4. Trailing number validation
    if len(text) >= 8 and text[-4:].isdigit():
        score += 0.10
        
    return min(1.0, score)

def perform_ocr_on_plate(plate_crop_bgr):
    """
    Executes multi-variant, multi-PSM OCR on the detected plate crop.
    Returns:
        dict containing:
        - raw_ocr: primary extracted text
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
    psm_modes = [6, 11, 7, 8, 13]
    whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    
    candidate_scores = {}
    candidate_counts = {}
    raw_texts = []
    
    for v_name, img_var in variants.items():
        for psm in psm_modes:
            # Try both whitelist-constrained and unconstrained OCR
            configs = [
                f"--oem 3 --psm {psm} -c tessedit_char_whitelist={whitelist}",
                f"--oem 3 --psm {psm}"
            ]
            for config in configs:
                try:
                    raw = pytesseract.image_to_string(img_var, config=config)
                    if not raw or not raw.strip():
                        continue
                    
                    # Extract individual lines and tokens
                    lines = [l.strip() for l in raw.splitlines() if l.strip()]
                    for line in lines:
                        # Clean whole line
                        cl = clean_ocr_text(line)
                        if cl and 5 <= len(cl) <= 12:
                            raw_texts.append(cl)
                            for cand in apply_indian_plate_corrections(cl):
                                candidate_counts[cand] = candidate_counts.get(cand, 0) + 1
                                struct_s = evaluate_plate_structure(cand)
                                vote_s = min(0.30, candidate_counts[cand] * 0.05)
                                total_s = struct_s + vote_s
                                if cand not in candidate_scores or total_s > candidate_scores[cand]:
                                    candidate_scores[cand] = total_s
                                    
                        # Also test space-delimited tokens joined
                        toks = [clean_ocr_text(t) for t in line.split() if clean_ocr_text(t)]
                        toks_filt = [t for t in toks if t not in ('I', 'L', '1') or len(toks) <= 3]
                        for token_list in (toks, toks_filt):
                            if len(token_list) >= 2:
                                joined = "".join(token_list)
                                if 5 <= len(joined) <= 12:
                                    for cand in apply_indian_plate_corrections(joined):
                                        candidate_counts[cand] = candidate_counts.get(cand, 0) + 1
                                        struct_s = evaluate_plate_structure(cand)
                                        vote_s = min(0.30, candidate_counts[cand] * 0.05)
                                        total_s = struct_s + vote_s
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
