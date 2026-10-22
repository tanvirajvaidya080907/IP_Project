import os
import sys
import torch
from ultralytics import YOLO

def train():
    print("=" * 50)
    print("DATASET USED FOR TRAINING")
    print("=" * 50)
    print("Source:")
    print("video_images")
    print("\nImages:")
    print("654 (Train: 523, Val: 65, Test: 66)")
    print("\nAnnotations:")
    print("654")
    print("\nClasses:")
    print("number_plate (id: 0)")
    print("\nOther dataset folders:")
    print("IGNORED")
    print("=" * 50)
    
    device = "0" if torch.cuda.is_available() else "cpu"
    print(f"\nTraining Device: {device} (CUDA available: {torch.cuda.is_available()})")
    
    # Path to yaml
    yaml_path = os.path.abspath("yolo_dataset/data.yaml")
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"data.yaml not found at {yaml_path}. Run prepare_yolo_dataset.py first.")

    # Base model - prefer local yolo11n.pt if present
    base_model = "yolo11n.pt" if os.path.exists("yolo11n.pt") else "yolo11n.pt"
    print(f"Loading base weights: {base_model}")
    model = YOLO(base_model)
    
    print("Starting YOLO training on video_images dataset...")
    results = model.train(
        data=yaml_path,
        epochs=20,
        imgsz=640,
        batch=16,
        device=device,
        project="runs/detect",
        name="number_plate_detector",
        exist_ok=True,
        workers=0,  # safe for Windows multiprocessing
        plots=True,
        verbose=True
    )
    
    best_weights_path = os.path.join("runs", "detect", "number_plate_detector", "weights", "best.pt")
    if os.path.exists(best_weights_path):
        print("\n" + "=" * 50)
        print("TRAINING SUCCESSFUL!")
        print(f"Best model saved to: {best_weights_path}")
        print("=" * 50)
    else:
        print(f"Warning: Expected best.pt at {best_weights_path}, please check runs folder.")

if __name__ == "__main__":
    train()
