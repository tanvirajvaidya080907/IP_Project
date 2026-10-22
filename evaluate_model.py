import os
import glob
from ultralytics import YOLO

def find_best_model():
    candidates = [
        os.path.join("runs", "detect", "number_plate_detector", "weights", "best.pt"),
        os.path.join("runs", "detect", "runs", "detect", "number_plate_detector", "weights", "best.pt"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return os.path.abspath(p)
    matches = glob.glob("runs/**/best.pt", recursive=True)
    if matches:
        return os.path.abspath(matches[0])
    if os.path.isfile("yolo11n.pt"):
        return os.path.abspath("yolo11n.pt")
    raise FileNotFoundError("Model weights not found.")

def evaluate():
    model_path = find_best_model()
    print("=" * 50)
    print("EVALUATING YOLO NUMBER-PLATE DETECTION MODEL")
    print("=" * 50)
    print(f"Model path: {model_path}")
    
    yaml_path = os.path.abspath("yolo_dataset/data.yaml")
    model = YOLO(model_path)
    
    print("\nRunning validation on validation set...")
    metrics_val = model.val(data=yaml_path, split="val", verbose=True)
    
    print("\n" + "=" * 50)
    print("VALIDATION METRICS SUMMARY")
    print("=" * 50)
    precision = float(metrics_val.box.p[0]) if len(metrics_val.box.p) > 0 else 0.0
    recall = float(metrics_val.box.r[0]) if len(metrics_val.box.r) > 0 else 0.0
    map50 = float(metrics_val.box.map50)
    map50_95 = float(metrics_val.box.map)
    
    print(f"Precision : {precision:.4f} ({precision * 100:.2f}%)")
    print(f"Recall    : {recall:.4f} ({recall * 100:.2f}%)")
    print(f"mAP50     : {map50:.4f} ({map50 * 100:.2f}%)")
    print(f"mAP50-95  : {map50_95:.4f} ({map50_95 * 100:.2f}%)")
    print("=" * 50)
    
    return {
        "precision": precision,
        "recall": recall,
        "map50": map50,
        "map50_95": map50_95
    }

if __name__ == "__main__":
    evaluate()
