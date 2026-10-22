import sqlite3
import difflib
import re
import os

DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vehicle_database.db")

# Common OCR confusion character mapping (bidirectional)
CONFUSION_PAIRS = {
    'O': '0', '0': 'O',
    'I': '1', '1': 'I',
    'L': '1', '1': 'L',
    'S': '5', '5': 'S',
    'B': '8', '8': 'B',
    'Z': '2', '2': 'Z',
    'G': '6', '6': 'G',
    'T': '7', '7': 'T',
    'D': '0', '0': 'D',
    'Q': '0', '0': 'Q',
    'A': '4', '4': 'A',
    'C': '0', '0': 'C',
}

def normalize_registration(text):
    """Clean registration text: uppercase, alphanumeric only."""
    if not text:
        return ""
    return re.sub(r'[^A-Z0-9]', '', str(text).upper())

def get_connection():
    if not os.path.exists(DATABASE_PATH):
        raise FileNotFoundError(f"Database not found at {DATABASE_PATH}. Run create_database.py first.")
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_all_database_plates():
    """Load all database vehicles into memory for high-speed matching."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vehicles")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def position_aware_similarity(candidate, target):
    """
    Computes an intelligent similarity score between candidate OCR and target DB plate.
    Considers:
    - Exact character matches
    - Known OCR character confusions (e.g. O<->0, B<->8, S<->5)
    - Indian plate structure (State, RTO, Series, Number)
    - Substring / prefix / suffix alignments
    """
    c = normalize_registration(candidate)
    t = normalize_registration(target)
    
    if not c or not t:
        return 0.0
    if c == t:
        return 1.0

    # 1. State code alignment check (first 2 chars)
    state_match = (c[:2] == t[:2])
    state_bonus = 0.15 if state_match else (-0.15 if len(c) >= 2 and len(t) >= 2 else 0.0)

    # 2. SequenceMatcher base ratio
    base_ratio = difflib.SequenceMatcher(None, c, t).ratio()

    # 3. Position-wise confusion-tolerant alignment
    min_len = min(len(c), len(t))
    max_len = max(len(c), len(t))
    match_score = 0.0

    for i in range(min_len):
        ch1 = c[i]
        ch2 = t[i]
        if ch1 == ch2:
            match_score += 1.0
        elif CONFUSION_PAIRS.get(ch1) == ch2 or CONFUSION_PAIRS.get(ch2) == ch1:
            match_score += 0.85  # Mild penalty for known optical confusion
        else:
            match_score += 0.0

    positional_ratio = match_score / max_len

    # 4. Partial substring / subsequence check
    sub_ratio = 0.0
    if c in t or t in c:
        sub_ratio = min_len / max_len

    # 5. Combined weighted score
    raw_score = 0.50 * positional_ratio + 0.35 * base_ratio + 0.15 * sub_ratio + state_bonus
    final_score = max(0.0, min(1.0, raw_score))
    return final_score

def find_best_vehicle_match(ocr_candidates, min_confidence=0.68):
    """
    Matches a list of OCR candidates against the vehicle database.
    
    Args:
        ocr_candidates: list of string candidates or single string
        min_confidence: minimum threshold (default 0.68)
        
    Returns:
        dict with keys: matched, registration_number, score, vehicle_info, match_type
    """
    if isinstance(ocr_candidates, str):
        ocr_candidates = [ocr_candidates]
        
    cleaned_candidates = [normalize_registration(c) for c in ocr_candidates if normalize_registration(c)]
    
    if not cleaned_candidates:
        return {
            "matched": False,
            "registration_number": "UNKNOWN",
            "score": 0.0,
            "vehicle_info": None,
            "match_type": "none",
            "message": "No valid OCR candidates provided"
        }

    db_vehicles = fetch_all_database_plates()
    db_lookup = {v["normalized_reg"]: v for v in db_vehicles}

    # Stage 1: Exact match with any candidate
    for cand in cleaned_candidates:
        if cand in db_lookup:
            return {
                "matched": True,
                "registration_number": cand,
                "score": 1.0,
                "vehicle_info": db_lookup[cand],
                "match_type": "exact",
                "message": "Exact database match confirmed"
            }

    # Stage 2: Best fuzzy/confusion match across all candidates and DB plates
    best_match = None
    best_score = 0.0
    best_candidate_used = cleaned_candidates[0]

    for cand in cleaned_candidates:
        for v in db_vehicles:
            target_reg = v["normalized_reg"]
            score = position_aware_similarity(cand, target_reg)
            if score > best_score:
                best_score = score
                best_match = v
                best_candidate_used = cand

    # Stage 3: Controlled threshold validation
    if best_match and best_score >= min_confidence:
        return {
            "matched": True,
            "registration_number": best_match["registration_number"],
            "score": round(best_score, 4),
            "vehicle_info": best_match,
            "match_type": "fuzzy_confusion",
            "candidate_used": best_candidate_used,
            "message": f"Strong database match with score {best_score:.2%}"
        }
    else:
        # Confidence too low -> Never invent a vehicle!
        return {
            "matched": False,
            "registration_number": cleaned_candidates[0],
            "score": round(best_score, 4),
            "vehicle_info": None,
            "match_type": "none",
            "candidate_used": best_candidate_used,
            "message": "Vehicle not found in database with high confidence"
        }
