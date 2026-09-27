import torch
from transformers import AutoProcessor, OmDetTurboForObjectDetection
from PIL import Image
import requests

# 先確認GPU狀況
print("CUDA available:", torch.cuda.is_available())
print("GPU name:", torch.cuda.get_device_name(0))
device = "cuda" if torch.cuda.is_available() else "cpu"

# 載入模型與processor（第一次執行會自動下載權重，存到 ~/.cache/huggingface）
print("Loading model...")
model_id = "omlab/omdet-turbo-swin-tiny-hf"
processor = AutoProcessor.from_pretrained(model_id)
model = OmDetTurboForObjectDetection.from_pretrained(model_id).to(device)

# 先用一張公開測試圖驗證pipeline通不通（COCO範例圖，有貓跟遙控器）
url = "http://images.cocodataset.org/val2017/000000039769.jpg"
image = Image.open(requests.get(url, stream=True).raw)

# 我們用跟居家老人情境相關的查詢詞先試（雖然這張圖是貓，只是驗證流程能跑）
text_queries = ["a cat", "a remote control"]

inputs = processor(image, text=text_queries, return_tensors="pt").to(device)

with torch.no_grad():
    outputs = model(**inputs)

results = processor.post_process_grounded_object_detection(
    outputs,
    target_sizes=[image.size[::-1]],
    text_labels=text_queries,
    threshold=0.3,
    nms_threshold=0.3,
)[0]

print("\n=== Detection Results ===")
for box, score, label in zip(results["boxes"], results["scores"], results["text_labels"]):
    box = [round(x, 1) for x in box.tolist()]
    print(f"Detected '{label}' with confidence {round(score.item(), 3)} at location {box}")

print("\nStep 2 complete — pipeline is working!")
