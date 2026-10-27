"""
test_fallback.py - Comprehensive verification suite for the Unknown Number Plate Fallback Feature.

Validates:
1. Plates present in database continue to return existing database profiles (Priority 1).
2. Valid Indian plates absent from database correctly resolve State & RTO Authority (Priority 2).
3. Unsupported/unknown RTO codes do not produce fabricated authority names.
4. Unsupported/unknown State codes gracefully return "Not Available".
5. Unreadable or malformed OCR outputs gracefully return "Not Available".
6. Fuel Type, Vehicle Age, and Registration Date strictly return "Not Available" when not in DB.
7. Database integrity: No records are inserted or altered by fallback queries.
8. Flask template rendering for both DB matched and fallback profiles.
"""

import sqlite3
import os
import unittest
from rto_lookup import (
    clean_registration_text,
    parse_indian_registration_format,
    lookup_rto_authority,
    resolve_registration_fallback,
    INDIAN_STATES,
    RTO_AUTHORITIES
)
from database import find_best_vehicle_match, get_connection
from app import app


class TestRegistrationFallback(unittest.TestCase):

    def setUp(self):
        self.app_client = app.test_client()

    def test_database_matched_plate_unchanged(self):
        """Scenario 1: Plate in database must produce the exact existing profile as before."""
        # Query an existing plate from the database
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vehicles LIMIT 1")
        row = dict(cursor.fetchone())
        conn.close()

        plate = row["registration_number"]
        match_result = find_best_vehicle_match(plate)

        self.assertTrue(match_result["matched"], f"Expected {plate} to match in database")
        self.assertEqual(match_result["registration_number"], plate)
        self.assertIsNotNone(match_result["vehicle_info"])
        self.assertEqual(match_result["vehicle_info"]["fuel_type"], row["fuel_type"])
        self.assertEqual(match_result["vehicle_info"]["state_name"], row["state_name"])
        self.assertEqual(match_result["vehicle_info"]["rto_code"], row["rto_code"])
        print(f"\n[PASS] Database match test for {plate}: Successfully retrieved existing profile.")

    def test_unfamiliar_plate_absent_from_database(self):
        """Scenario 2 & 3: Valid plate absent from DB must infer State and RTO authority."""
        # 'MH02AB1234' is absent from the local database
        plate = "MH02AB1234"

        # Verify it's not in the database
        db_match = find_best_vehicle_match(plate)
        self.assertFalse(db_match["matched"], f"Plate {plate} should not be in vehicle_database.db")

        # Resolve fallback
        fb = resolve_registration_fallback(plate)
        self.assertTrue(fb["is_valid_format"])
        self.assertEqual(fb["registration_number"], "MH02AB1234")
        self.assertEqual(fb["state"], "Maharashtra (MH)")
        self.assertIn("MH-02", fb["rto_authority"])
        self.assertIn("Mumbai West", fb["rto_authority"])
        self.assertEqual(fb["fuel_type"], "Not Available")
        self.assertEqual(fb["vehicle_age"], "Not Available")
        self.assertEqual(fb["registration_date"], "Not Available")
        self.assertEqual(fb["source"], "Registration Code Lookup")
        print(f"[PASS] Unfamiliar plate {plate}: State='{fb['state']}', RTO='{fb['rto_authority']}'")

        # Also test the user's example plate MH02DN8718 through the fallback module directly
        user_example_fb = resolve_registration_fallback("MH02DN8718")
        self.assertEqual(user_example_fb["registration_number"], "MH02DN8718")
        self.assertEqual(user_example_fb["state"], "Maharashtra (MH)")
        self.assertIn("MH-02", user_example_fb["rto_authority"])
        self.assertIn("Mumbai West", user_example_fb["rto_authority"])
        print(f"[PASS] User example MH02DN8718 directly in fallback: State='{user_example_fb['state']}', RTO='{user_example_fb['rto_authority']}'")

    def test_various_state_rto_codes(self):
        """Test inference across multiple major states absent from DB."""
        test_cases = [
            ("DL01AB1234", "Delhi (DL)", "DL-01", "Mall Road"),
            ("KA01MB9999", "Karnataka (KA)", "KA-01", "Koramangala"),
            ("GJ01AX5555", "Gujarat (GJ)", "GJ-01", "Ahmedabad"),
            ("TN01BB4321", "Tamil Nadu (TN)", "TN-01", "Ayanavaram"),
            ("UP14CD9999", "Uttar Pradesh (UP)", "UP-14", "Ghaziabad"),
            ("TS09FA1234", "Telangana (TS)", "TS-09", "Hyderabad Central"),
            ("KL01AZ1111", "Kerala (KL)", "KL-01", "Thiruvananthapuram"),
            ("HR26DK8888", "Haryana (HR)", "HR-26", "Gurugram"),
        ]

        for reg, expected_state, expected_rto_code, expected_loc in test_cases:
            fb = resolve_registration_fallback(reg)
            self.assertTrue(fb["is_valid_format"])
            self.assertEqual(fb["state"], expected_state)
            self.assertIn(expected_rto_code, fb["rto_authority"])
            self.assertIn(expected_loc, fb["rto_authority"])
            self.assertEqual(fb["fuel_type"], "Not Available")
            self.assertEqual(fb["vehicle_age"], "Not Available")
            self.assertEqual(fb["registration_date"], "Not Available")
            print(f"[PASS] Mapped code {reg} -> {fb['state']} | {fb['rto_authority']}")

    def test_unsupported_rto_code_no_fabrication(self):
        """Scenario 4: Unknown RTO code under a valid state must NOT produce fabricated authority."""
        # MH99 is not a valid RTO in mapping
        fb = resolve_registration_fallback("MH99ZZ9999")
        self.assertTrue(fb["is_valid_format"])
        self.assertEqual(fb["state"], "Maharashtra (MH)")
        self.assertEqual(fb["rto_authority"], "Not Available", "Must not fabricate RTO name for unknown code")
        print(f"[PASS] Unmapped RTO code MH99ZZ9999 correctly returned RTO Authority: 'Not Available'")

    def test_invalid_state_code(self):
        """Scenario 4 & 5: Invalid state prefix must not fabricate state or RTO."""
        fb = resolve_registration_fallback("ZZ01AB1234")
        self.assertEqual(fb["state"], "Not Available")
        self.assertEqual(fb["rto_authority"], "Not Available")
        print(f"[PASS] Invalid state ZZ01AB1234 correctly returned State & RTO: 'Not Available'")

    def test_malformed_unreadable_ocr(self):
        """Scenario 5: Malformed or unreadable OCR string gracefully handled."""
        for garbled in ["UNKNOWN", "XYZ", "12345", "!!!???", ""]:
            fb = resolve_registration_fallback(garbled)
            self.assertFalse(fb["is_valid_format"])
            self.assertEqual(fb["state"], "Not Available")
            self.assertEqual(fb["rto_authority"], "Not Available")
            self.assertEqual(fb["fuel_type"], "Not Available")
            self.assertEqual(fb["vehicle_age"], "Not Available")
            self.assertEqual(fb["registration_date"], "Not Available")
        print(f"[PASS] Garbled/Empty inputs handled gracefully without raising exceptions.")

    def test_ocr_confusion_resilience(self):
        """Test optical confusion handling (e.g. MHO2 instead of MH02)."""
        fb = resolve_registration_fallback("MHO2DN8718")
        self.assertTrue(fb["is_valid_format"])
        self.assertEqual(fb["state"], "Maharashtra (MH)")
        self.assertIn("MH-02", fb["rto_authority"])
        print(f"[PASS] OCR optical confusion 'MHO2' successfully resolved to 'MH-02'.")

    def test_database_not_modified_by_fallback(self):
        """Scenario 9: Fallback lookups must NEVER insert records into SQLite database."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM vehicles")
        count_before = cursor.fetchone()[0]
        conn.close()

        # Run several fallback lookups
        resolve_registration_fallback("MH02DN8718")
        resolve_registration_fallback("KA01AB1234")
        resolve_registration_fallback("RANDOM9999")

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM vehicles")
        count_after = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count_before, count_after, "Database record count must remain identical")
        print(f"[PASS] Database isolation confirmed: vehicle count remained {count_before}.")

    def test_template_rendering_for_both_modes(self):
        """Scenario 8: Test that vehicle_identified.html renders properly for both matched and fallback."""
        from flask import render_template
        with app.test_request_context():
            # 1. Matched vehicle template test
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vehicles LIMIT 1")
            v_row = dict(cursor.fetchone())
            conn.close()

            matched_payload = {
                "registration_number": v_row["registration_number"],
                "confidence": 0.95,
                "bbox": [100, 100, 200, 200],
                "debug_image_filename": "dummy_debug.jpg",
                "crop_image_filename": "dummy_crop.jpg",
                "ocr": {"selected_ocr": v_row["registration_number"], "raw_ocr": v_row["registration_number"], "ocr_candidates": [v_row["registration_number"]]},
                "db_match": {
                    "matched": True,
                    "registration_number": v_row["registration_number"],
                    "score": 1.0,
                    "vehicle_info": v_row,
                    "match_type": "exact"
                },
                "fallback_profile": None
            }
            html_matched = render_template('vehicle_identified.html', result=matched_payload, analysis_id="TESTMATCH")
            self.assertIn("MATCHED", html_matched)
            self.assertIn(v_row["registration_number"], html_matched)
            self.assertIn(v_row["state_name"], html_matched)
            self.assertIn(str(v_row["vehicle_age"]), html_matched)
            print("[PASS] Template rendered successfully for DATABASE MATCHED vehicle.")

            # 2. Fallback vehicle template test (MH02DN8718)
            fb_profile = resolve_registration_fallback("MH02DN8718")
            fallback_payload = {
                "registration_number": "MH02DN8718",
                "confidence": 0.92,
                "bbox": [120, 120, 250, 180],
                "debug_image_filename": "dummy_debug.jpg",
                "crop_image_filename": "dummy_crop.jpg",
                "ocr": {"selected_ocr": "MH02DN8718", "raw_ocr": "MH02DN8718", "ocr_candidates": ["MH02DN8718"]},
                "db_match": {
                    "matched": False,
                    "registration_number": "MH02DN8718",
                    "score": 0.0,
                    "vehicle_info": None,
                    "match_type": "none"
                },
                "fallback_profile": fb_profile
            }
            html_fallback = render_template('vehicle_identified.html', result=fallback_payload, analysis_id="TESTFALLBACK")
            self.assertIn("NOT FOUND", html_fallback)
            self.assertIn("Registration Code Lookup", html_fallback)
            self.assertIn("MH02DN8718", html_fallback)
            self.assertIn("Maharashtra (MH)", html_fallback)
            self.assertIn("Mumbai West", html_fallback)
            self.assertIn("Not Available", html_fallback)
            self.assertIn("No matching record in local database", html_fallback)
            print("[PASS] Template rendered successfully for UNKNOWN / FALLBACK vehicle with 6 profile fields.")


if __name__ == '__main__':
    unittest.main()
