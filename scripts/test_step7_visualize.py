import cv2
from ultralytics import YOLO
from collections import Counter

model = YOLO("yolov8n-pose.pt")

def classify_pose(keypoints):
    xs = keypoints[:, 0]
    ys = keypoints[:, 1]
    valid = (xs > 0) & (ys > 0)
    if valid.sum() < 5:
        return "uncertain"
    xs, ys = xs[valid], ys[valid]
    width = xs.max() - xs.min()
    height = ys.max() - ys.min()
    if height == 0:
        return "uncertain"
    if width / height > 1.0:
        return "lying on the floor"
    shoulder_y = (keypoints[5][1] + keypoints[6][1]) / 2
    hip_y = (keypoints[11][1] + keypoints[12][1]) / 2
    ankle_y = (keypoints[15][1] + keypoints[16][1]) / 2
    torso_height = hip_y - shoulder_y
    leg_height = ankle_y - hip_y
    if torso_height < 5 or leg_height < 5:
        return "uncertain"
    leg_to_torso_ratio = leg_height / torso_height
    return "standing" if leg_to_torso_ratio > 1.3 else "sitting"


def visualize_video(input_path, output_path, sample_fps=5, alert_duration_sec=2.0):
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"⚠ Cannot open {input_path}")
        return

    native_fps = cap.get(cv2.CAP_PROP_FPS)
    width_px = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height_px = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_interval = max(1, int(native_fps / sample_fps))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, native_fps, (width_px, height_px))

    # 狀態追蹤（跟 Step 5 的核心邏輯相同）
    pose_history = []       # 最近幾次抽樣的姿態，做眾數濾波
    prev_pose = None
    entered_lying = False
    exit_lying_time = None
    current_pose_label = "detecting..."
    alert_text = None
    alert_until_time = -1

    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        timestamp = frame_idx / native_fps

        if frame_idx % frame_interval == 0:
            results = model(frame, verbose=False)

            if len(results[0].keypoints.xy) > 0:
                kpts = results[0].keypoints.xy[0].cpu().numpy()
                raw_pose = classify_pose(kpts)
            else:
                raw_pose = "no person detected"

            # 簡易眾數濾波（用最近5次抽樣）
            pose_history.append(raw_pose)
            if len(pose_history) > 5:
                pose_history.pop(0)
            current_pose_label = Counter(pose_history).most_common(1)[0][0]

            # 跌倒事件判斷（同Step5邏輯）
            if current_pose_label == "lying on the floor":
                if not entered_lying:
                    entered_lying = True
                    if prev_pose == "standing":
                        alert_text = "FALL DETECTED"
                        alert_until_time = timestamp + alert_duration_sec
                    elif prev_pose == "sitting":
                        alert_text = "Normal lying down"
                        alert_until_time = timestamp + alert_duration_sec
                exit_lying_time = None
            else:
                if entered_lying:
                    if exit_lying_time is None:
                        exit_lying_time = timestamp
                    elif timestamp - exit_lying_time >= 1.0:
                        entered_lying = False
                if current_pose_label in ("standing", "sitting"):
                    prev_pose = current_pose_label

            # 畫骨架關鍵點（用YOLO內建畫圖工具）
            annotated = results[0].plot()
            frame = annotated

        # 疊字：目前姿態（每幀都畫，用最近一次分類結果）
        cv2.putText(frame, f"Pose: {current_pose_label}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, f"t={timestamp:.1f}s", (20, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2, cv2.LINE_AA)

        # 疊字：警示訊息（跌倒/正常臥床，持續顯示幾秒）
        if alert_text and timestamp <= alert_until_time:
            color = (0, 0, 255) if alert_text == "FALL DETECTED" else (0, 200, 0)
            cv2.putText(frame, alert_text, (20, height_px - 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3, cv2.LINE_AA)

        out.write(frame)
        frame_idx += 1

    cap.release()
    out.release()
    print(f"Saved: {output_path}")


visualize_video("../test_videos/fall_event.mp4", "../outputs/fall_event_annotated.mp4")
visualize_video("../test_videos/normal_lying.mp4", "../outputs/normal_lying_annotated.mp4")
