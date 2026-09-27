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


def analyze_video(video_path, sample_fps=5):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"⚠ Cannot open {video_path}")
        return []
    native_fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = max(1, int(native_fps / sample_fps))
    timeline = []
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % frame_interval == 0:
            timestamp = frame_idx / native_fps
            results = model(frame, verbose=False)
            if len(results[0].keypoints.xy) > 0:
                kpts = results[0].keypoints.xy[0].cpu().numpy()
                pose = classify_pose(kpts)
            else:
                pose = "no person detected"
            timeline.append((round(timestamp, 2), pose))
        frame_idx += 1
    cap.release()
    return timeline


def mode_filter(timeline, window=3):
    """置中式眾數濾波：看前後鄰居，多數決；平手則保留原值。濾除孤立單幀雜訊，保留真實短暫轉換。"""
    poses = [p for _, p in timeline]
    filtered = []
    half = window // 2
    for i in range(len(poses)):
        lo = max(0, i - half)
        hi = min(len(poses), i + half + 1)
        window_poses = poses[lo:hi]
        counts = Counter(window_poses)
        most_common = counts.most_common()
        top_count = most_common[0][1]
        candidates = [p for p, c in most_common if c == top_count]
        # 平手時保留原值，避免任意選擇
        chosen = poses[i] if poses[i] in candidates else most_common[0][0]
        filtered.append((timeline[i][0], chosen))
    return filtered


def detect_fall_events(timeline, min_exit_duration=1.0):
    """
    min_exit_duration: 離開lying狀態要維持至少這麼多秒，才視為「真的起身了」，
    否則視為雜訊抖動，忽略、繼續當作還在lying。
    """
    events = []
    prev_pose = None       # 最近一次穩定的 standing/sitting
    entered_lying = False
    exit_lying_time = None  # 記錄「疑似離開lying」的時間點

    for t, pose in timeline:
        if pose == "lying on the floor":
            if not entered_lying:
                entered_lying = True
                if prev_pose == "sitting":
                    events.append((t, "normal lying down (transitioned via sitting)"))
                elif prev_pose == "standing":
                    events.append((t, "FALL DETECTED (direct standing-to-lying, no sitting phase)"))
                else:
                    events.append((t, f"lying detected (previous stable state: {prev_pose})"))
            exit_lying_time = None  # 回到lying，取消「離開」的計時
        else:
            if entered_lying:
                if exit_lying_time is None:
                    exit_lying_time = t  # 剛開始疑似離開
                elif t - exit_lying_time >= min_exit_duration:
                    entered_lying = False  # 離開夠久了，確認真的起身
            if pose in ("standing", "sitting"):
                prev_pose = pose

    return events


videos = ["../test_videos/fall_event.mp4", "../test_videos/normal_lying.mp4"]

for video_path in videos:
    print(f"\n{'='*50}\nAnalyzing: {video_path}\n{'='*50}")
    raw_timeline = analyze_video(video_path, sample_fps=5)
    filtered_timeline = mode_filter(raw_timeline, window=3)

    events = detect_fall_events(filtered_timeline, min_exit_duration=1.0)
    print("\n-- Event Detection Result --")
    if not events:
        print("  No lying event detected")
    for t, verdict in events:
        print(f"  At t={t}s: {verdict}")
