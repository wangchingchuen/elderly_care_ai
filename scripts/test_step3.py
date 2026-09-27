import torch
from transformers import AutoProcessor, OmDetTurboForObjectDetection
from PIL import Image
import os

device = "cuda" if torch.cuda.is_available() else "cpu"
model_id = "omlab/omdet-turbo-swin-tiny-hf"
processor = AutoProcessor.from_pretrained(model_id)
model = OmDetTurboForObjectDetection.from_pretrained(model_id).to(device)

# 你的三種姿態查詢詞
text_queries = ["a person standing", "a person sitting", "a person lying on the floor"]

test_dir = "../test_photos"
test_images = ["standing.png", "sitting.png", "lying.png"]

for img_name in test_images:
    img_path = os.path.join(test_dir, img_name)
    if not os.path.exists(img_path):
        print(f"⚠ Skip {img_name} — file not found")
        continue

    image = Image.open(img_path).convert("RGB")
    inputs = processor(image, text=text_queries, return_tensors="pt").to(device)

    with torch.no_grad():
        outputs = model(**inputs)

    results = processor.post_process_grounded_object_detection(
        outputs,
        target_sizes=[image.size[::-1]],
        text_labels=text_queries,
        threshold=0.15,   # 先設低一點，人體姿態比物件難認，方便觀察全部候選
        nms_threshold=0.3,
    )[0]

    print(f"\n=== {img_name} ===")
    if len(results["scores"]) == 0:
        print("  No detections above threshold")
    for score, label in zip(results["scores"], results["text_labels"]):
        print(f"  '{label}' — confidence {round(score.item(), 3)}")
