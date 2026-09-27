import torch
from transformers import AutoProcessor, OmDetTurboForObjectDetection
from PIL import Image
import cv2
import os

device = "cuda" if torch.cuda.is_available() else "cpu"
model_id = "omlab/omdet-turbo-swin-tiny-hf"
processor = AutoProcessor.from_pretrained(model_id)
model = OmDetTurboForObjectDetection.from_pretrained(model_id).to(device)

text_queries = [
    "a person eating food",
    "a person watching television",
    "a person using a computer",
]

video_path = "../test_videos/activity_2.mp4"
sample_fps = 2  # 每秒抽2幀，跟你App目前設定接近

cap = cv2.VideoCapture(video_path)
native_fps = cap.get(cv2.CAP_PROP_FPS) or 25
frame_interval = max(1, int(native_fps / sample_fps))

frame_idx = 0
while True:
    ret, frame = cap.read()
    if not ret:
        break

    if frame_idx % frame_interval == 0:
        timestamp = frame_idx / native_fps
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        inputs = processor(image, text=text_queries, return_tensors="pt").to(device)

        with torch.no_grad():
            outputs = model(**inputs)

        results = processor.post_process_grounded_object_detection(
            outputs, target_sizes=[image.size[::-1]], text_labels=text_queries,
            threshold=0.1, nms_threshold=0.3,
        )[0]

        print(f"\n=== t={timestamp:.1f}s ===")
        if len(results["scores"]) == 0:
            print("  No detections above threshold")
        else:
            # 依信心分數排序，方便看
            pairs = sorted(zip(results["scores"], results["text_labels"]), key=lambda x: -x[0])
            for score, label in pairs:
                print(f"  '{label}' — confidence {round(score.item(), 3)}")

    frame_idx += 1

cap.release()
