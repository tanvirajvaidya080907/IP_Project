import os
import shutil
import random
import xml.etree.ElementTree as ET
from PIL import Image

def prepare_yolo_dataset(
    source_dir="dataset/video_images",
    output_dir="yolo_dataset",
    train_ratio=0.80,
    val_ratio=0.10,
    test_ratio=0.10,
    seed=42
):
    print("=" * 60)
    print("        PREPARING YOLO NUMBER-PLATE DATASET")
    print("=" * 60)
    print(f"Source Directory: {source_dir}")
    print(f"Output Directory: {output_dir}")
    
    if not os.path.exists(source_dir):
        raise FileNotFoundError(f"Source directory {source_dir} not found!")

    # Check and list all images
    all_files = os.listdir(source_dir)
    image_exts = ('.jpg', '.jpeg', '.png')
    image_files = sorted([f for f in all_files if f.lower().endswith(image_exts)])
    
    print(f"Total images found in video_images: {len(image_files)}")
    
    # Pair with XMLs
    valid_pairs = []
    skipped_files = []
    
    for img_name in image_files:
        base_name = os.path.splitext(img_name)[0]
        xml_name = base_name + ".xml"
        xml_path = os.path.join(source_dir, xml_name)
        img_path = os.path.join(source_dir, img_name)
        
        if not os.path.exists(xml_path):
            skipped_files.append((img_name, "XML file not found"))
            continue
            
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            objects = root.findall("object")
            if not objects:
                skipped_files.append((img_name, "No <object> in XML"))
                continue
                
            # Get actual image size from PIL to ensure exact dimensions
            with Image.open(img_path) as im:
                width, height = im.size
                
            boxes = []
            for obj in objects:
                bnd = obj.find("bndbox")
                if bnd is None:
                    continue
                xmin = float(bnd.find("xmin").text)
                ymin = float(bnd.find("ymin").text)
                xmax = float(bnd.find("xmax").text)
                ymax = float(bnd.find("ymax").text)
                
                # Sanity check and clamp coordinates
                xmin = max(0.0, min(xmin, float(width)))
                xmax = max(0.0, min(xmax, float(width)))
                ymin = max(0.0, min(ymin, float(height)))
                ymax = max(0.0, min(ymax, float(height)))
                
                if xmax <= xmin or ymax <= ymin:
                    continue
                    
                # Convert to normalized YOLO format: class x_center y_center width height
                x_center = ((xmin + xmax) / 2.0) / width
                y_center = ((ymin + ymax) / 2.0) / height
                box_w = (xmax - xmin) / width
                box_h = (ymax - ymin) / height
                
                # Ensure values are strictly within (0, 1]
                x_center = max(0.001, min(0.999, x_center))
                y_center = max(0.001, min(0.999, y_center))
                box_w = max(0.001, min(1.0, box_w))
                box_h = max(0.001, min(1.0, box_h))
                
                boxes.append((0, x_center, y_center, box_w, box_h))
                
            if not boxes:
                skipped_files.append((img_name, "No valid bounding box"))
                continue
                
            valid_pairs.append((img_name, img_path, boxes))
        except Exception as e:
            skipped_files.append((img_name, f"Parse error: {e}"))

    print(f"Valid image-annotation pairs: {len(valid_pairs)}")
    if skipped_files:
        print(f"Skipped files: {len(skipped_files)}")
        for f, reason in skipped_files[:5]:
            print(f"  - {f}: {reason}")

    # Reproducible Split: 80% train, 10% val, 10% test
    random.seed(seed)
    random.shuffle(valid_pairs)
    
    total = len(valid_pairs)
    train_end = int(total * train_ratio)
    val_end = train_end + int(total * val_ratio)
    
    splits = {
        "train": valid_pairs[:train_end],
        "val": valid_pairs[train_end:val_end],
        "test": valid_pairs[val_end:]
    }
    
    # Create directories
    for split in ["train", "val", "test"]:
        os.makedirs(os.path.join(output_dir, "images", split), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "labels", split), exist_ok=True)

    # Clean existing files in output dirs to avoid stale files
    for split in ["train", "val", "test"]:
        for d in ["images", "labels"]:
            target_p = os.path.join(output_dir, d, split)
            for f in os.listdir(target_p):
                os.remove(os.path.join(target_p, f))

    # Write files
    for split, pairs in splits.items():
        print(f"Writing {split} set: {len(pairs)} samples...")
        for img_name, img_path, boxes in pairs:
            # Copy image
            dst_img = os.path.join(output_dir, "images", split, img_name)
            shutil.copy2(img_path, dst_img)
            
            # Write YOLO label file (.txt)
            base_name = os.path.splitext(img_name)[0]
            label_name = base_name + ".txt"
            dst_label = os.path.join(output_dir, "labels", split, label_name)
            with open(dst_label, "w", encoding="utf-8") as lf:
                for cls_id, xc, yc, bw, bh in boxes:
                    lf.write(f"{cls_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}\n")

    # Generate data.yaml with absolute/relative path
    abs_output = os.path.abspath(output_dir).replace("\\", "/")
    data_yaml_content = f"""path: {abs_output}
train: images/train
val: images/val
test: images/test

nc: 1
names:
  0: number_plate
"""
    yaml_path = os.path.join(output_dir, "data.yaml")
    with open(yaml_path, "w", encoding="utf-8") as yf:
        yf.write(data_yaml_content)

    print("\n" + "=" * 60)
    print("DATASET PREPARATION COMPLETE")
    print("=" * 60)
    print(f"Train samples : {len(splits['train'])}")
    print(f"Val samples   : {len(splits['val'])}")
    print(f"Test samples  : {len(splits['test'])}")
    print(f"data.yaml created at: {yaml_path}")
    print("=" * 60)

if __name__ == "__main__":
    prepare_yolo_dataset()
