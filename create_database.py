import os
import sqlite3
import hashlib
import glob
import xml.etree.ElementTree as ET
from datetime import datetime

DATABASE_FILE = "vehicle_database.db"

STATE_MAP = {
    "AN": "Andaman and Nicobar",
    "AP": "Andhra Pradesh",
    "AR": "Arunachal Pradesh",
    "AS": "Assam",
    "BR": "Bihar",
    "CG": "Chhattisgarh",
    "CH": "Chandigarh",
    "DD": "Daman and Diu",
    "DL": "Delhi",
    "DN": "Dadra and Nagar Haveli",
    "GA": "Goa",
    "GJ": "Gujarat",
    "HP": "Himachal Pradesh",
    "HR": "Haryana",
    "JH": "Jharkhand",
    "JK": "Jammu and Kashmir",
    "KA": "Karnataka",
    "KL": "Kerala",
    "LA": "Ladakh",
    "LD": "Lakshadweep",
    "MH": "Maharashtra",
    "ML": "Meghalaya",
    "MN": "Manipur",
    "MP": "Madhya Pradesh",
    "MZ": "Mizoram",
    "NL": "Nagaland",
    "OD": "Odisha",
    "PB": "Punjab",
    "PY": "Puducherry",
    "RJ": "Rajasthan",
    "SK": "Sikkim",
    "TN": "Tamil Nadu",
    "TR": "Tripura",
    "TS": "Telangana",
    "UK": "Uttarakhand",
    "UP": "Uttar Pradesh",
    "WB": "West Bengal"
}

RTO_LOCATIONS = {
    "MH01": "Mumbai South (Tardeo)",
    "MH02": "Mumbai West (Andheri)",
    "MH03": "Mumbai East (Wadala)",
    "MH04": "Thane",
    "MH05": "Kalyan",
    "MH12": "Pune",
    "MH14": "Pimpri-Chinchwad",
    "MH20": "Aurangabad",
    "MH43": "Navi Mumbai (Vashi)",
    "MH46": "Panvel",
    "MH47": "Mumbai North (Borivali)",
    "MH48": "Vasai-Virar",
    "DL01": "Delhi North (Mall Road)",
    "DL03": "Delhi South (Sheikh Sarai)",
    "DL08": "Delhi North West (Wazirpur)",
    "DL3C": "Delhi South",
    "DL8C": "Delhi North West",
    "GJ12": "Bhuj (Kutch)",
    "GJ15": "Valsad"
}

CAR_PROFILES = [
    ("Maruti Suzuki", "Swift", "Hatchback", "Petrol"),
    ("Maruti Suzuki", "Baleno", "Hatchback", "Petrol"),
    ("Maruti Suzuki", "Dzire", "Sedan", "CNG"),
    ("Hyundai", "Creta", "SUV", "Diesel"),
    ("Hyundai", "i20", "Hatchback", "Petrol"),
    ("Hyundai", "Venue", "Compact SUV", "Petrol"),
    ("Tata Motors", "Nexon", "Compact SUV", "Diesel"),
    ("Tata Motors", "Harrier", "SUV", "Diesel"),
    ("Tata Motors", "Altroz", "Hatchback", "Petrol"),
    ("Honda", "City", "Sedan", "Petrol"),
    ("Honda", "Amaze", "Sedan", "Petrol"),
    ("Toyota", "Innova Crysta", "MPV", "Diesel"),
    ("Toyota", "Fortuner", "SUV", "Diesel"),
    ("Mahindra", "Scorpio-N", "SUV", "Diesel"),
    ("Mahindra", "XUV700", "SUV", "Diesel"),
    ("Mahindra", "Thar", "SUV", "Diesel"),
    ("Kia", "Seltos", "SUV", "Petrol"),
    ("Kia", "Sonet", "Compact SUV", "Diesel"),
    ("Volkswagen", "Taigun", "SUV", "Petrol"),
    ("Skoda", "Slavia", "Sedan", "Petrol")
]

def generate_deterministic_profile(reg_num):
    reg_clean = "".join(ch for ch in reg_num.upper() if ch.isalnum())
    # Deterministic pseudo-random seed from plate string hash
    hash_int = int(hashlib.sha256(reg_clean.encode('utf-8')).hexdigest()[:8], 16)
    
    # State code
    state_code = reg_clean[:2]
    state_name = STATE_MAP.get(state_code, f"State ({state_code})")
    
    # RTO code
    rto_code = reg_clean[:4]
    rto_name = RTO_LOCATIONS.get(rto_code, f"{state_name} RTO ({rto_code})")
    
    # Pick profile
    profile = CAR_PROFILES[hash_int % len(CAR_PROFILES)]
    manufacturer, model, v_class, fuel = profile
    
    # Manufacturing year (2014 to 2024)
    year = 2014 + (hash_int % 11)
    current_year = 2026
    age = current_year - year
    
    # Deterministic registration date
    month = 1 + ((hash_int // 11) % 12)
    day = 1 + ((hash_int // 132) % 28)
    reg_date = f"{year}-{month:02d}-{day:02d}"
    
    return {
        "registration_number": reg_clean,
        "state_code": state_code,
        "state_name": state_name,
        "rto_code": rto_code,
        "vehicle_class": v_class,
        "manufacturer": manufacturer,
        "model": model,
        "fuel_type": fuel,
        "manufacturing_year": year,
        "vehicle_age": age,
        "registration_date": reg_date,
        "is_synthetic_metadata": 1
    }

def create_database(xml_dir="dataset/video_images"):
    print("=" * 60)
    print("        CREATING VEHICLE DATABASE")
    print("=" * 60)
    
    # Connect SQLite
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vehicles (
        vehicle_id INTEGER PRIMARY KEY AUTOINCREMENT,
        registration_number TEXT UNIQUE NOT NULL,
        normalized_reg TEXT NOT NULL,
        state_code TEXT NOT NULL,
        state_name TEXT NOT NULL,
        rto_code TEXT NOT NULL,
        vehicle_class TEXT NOT NULL,
        manufacturer TEXT NOT NULL,
        model TEXT NOT NULL,
        fuel_type TEXT NOT NULL,
        manufacturing_year INTEGER NOT NULL,
        vehicle_age INTEGER NOT NULL,
        registration_date TEXT NOT NULL,
        is_synthetic_metadata INTEGER DEFAULT 1
    )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reg ON vehicles(registration_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_norm_reg ON vehicles(normalized_reg)")
    
    # Extract unique registration numbers from video_images XML files
    xml_files = glob.glob(os.path.join(xml_dir, "*.xml"))
    found_plates = set()
    
    for xml_path in xml_files:
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            for obj in root.findall("object"):
                name = obj.find("name")
                if name is not None and name.text:
                    p = name.text.strip().upper()
                    clean = "".join(c for c in p if c.isalnum())
                    if clean:
                        found_plates.add(clean)
        except Exception as e:
            print(f"Error reading {xml_path}: {e}")
            
    print(f"Extracted {len(found_plates)} unique registration numbers from {len(xml_files)} XML annotations.")
    
    # Insert records
    inserted = 0
    for plate in sorted(found_plates):
        data = generate_deterministic_profile(plate)
        norm_reg = data["registration_number"].replace(" ", "").upper()
        
        cursor.execute("""
        INSERT OR REPLACE INTO vehicles (
            registration_number, normalized_reg, state_code, state_name,
            rto_code, vehicle_class, manufacturer, model,
            fuel_type, manufacturing_year, vehicle_age, registration_date,
            is_synthetic_metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["registration_number"],
            norm_reg,
            data["state_code"],
            data["state_name"],
            data["rto_code"],
            data["vehicle_class"],
            data["manufacturer"],
            data["model"],
            data["fuel_type"],
            data["manufacturing_year"],
            data["vehicle_age"],
            data["registration_date"],
            data["is_synthetic_metadata"]
        ))
        inserted += 1
        
    conn.commit()
    conn.close()
    
    print(f"Database successfully populated with {inserted} vehicle records.")
    print(f"Database path: {os.path.abspath(DATABASE_FILE)}")
    print("=" * 60)

if __name__ == "__main__":
    create_database()
