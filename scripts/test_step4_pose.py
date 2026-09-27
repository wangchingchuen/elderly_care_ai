from ultralytics import YOLO
import os

# YOLOv8-pose 預訓練模型，第一次執行會自動下載
model = YOLO("yolov8n-pose.pt")

test_dir = "../test_photos"
test_images = ["standing.png", "sitting.png", "lying.png"]

def classify_pose(keypoints):
    xs = keypoints[:, 0]
    ys = keypoints[:, 1]

    # 過濾掉座標是(0,0)的無效關鍵點（沒偵測到的部位）
    valid = (xs > 0) & (ys > 0)
    if valid.sum() < 5:
        return "uncertain (too few keypoints)"

    xs, ys = xs[valid], ys[valid]
    width = xs.max() - xs.min()
    height = ys.max() - ys.min()

    print(f"    [debug] bbox width={width:.1f}, height={height:.1f}, aspect(w/h)={width/height:.2f}")

    # 身體外框「寬 > 高」，很可能是躺姿
    if width / height > 1.0:
        return "lying on the floor"

    # 不是躺姿的話，再用垂直距離比例分站/坐
    shoulder_y = (keypoints[5][1] + keypoints[6][1]) / 2
    hip_y = (keypoints[11][1] + keypoints[12][1]) / 2
    ankle_y = (keypoints[15][1] + keypoints[16][1]) / 2

    torso_height = hip_y - shoulder_y
    leg_height = ankle_y - hip_y

    if torso_height < 5 or leg_height < 5:
        return "uncertain (keypoints unclear)"

    leg_to_torso_ratio = leg_height / torso_height
    print(f"    [debug] leg_to_torso_ratio={leg_to_torso_ratio:.2f}")

    if leg_to_torso_ratio > 1.3:
        return "standing"
    else:
        return "sitting"

for img_name in test_images:
    img_path = os.path.join(test_dir, img_name)
    if not os.path.exists(img_path):
        print(f"⚠ Skip {img_name} — file not found")
        continue

    results = model(img_path, verbose=False)
    print(f"\n=== {img_name} ===")

    if len(results[0].keypoints.xy) == 0:
        print("  No person detected")
        continue

    for i, kpts in enumerate(results[0].keypoints.xy):
        kpts = kpts.cpu().numpy()
        pose = classify_pose(kpts)
        print(f"  Person {i+1}: classified as '{pose}'")
