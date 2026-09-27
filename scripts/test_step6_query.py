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
        chosen = poses[i] if poses[i] in candidates else most_common[0][0]
        filtered.append((timeline[i][0], chosen))
    return filtered


def detect_fall_events(timeline, min_exit_duration=1.0):
    events = []
    prev_pose = None
    entered_lying = False
    exit_lying_time = None
    for t, pose in timeline:
        if pose == "lying on the floor":
            if not entered_lying:
                entered_lying = True
                if prev_pose == "sitting":
                    events.append((t, "normal_lying"))
                elif prev_pose == "standing":
                    events.append((t, "fall"))
                else:
                    events.append((t, "lying_unknown_origin"))
            exit_lying_time = None
        else:
            if entered_lying:
                if exit_lying_time is None:
                    exit_lying_time = t
                elif t - exit_lying_time >= min_exit_duration:
                    entered_lying = False
            if pose in ("standing", "sitting"):
                prev_pose = pose
    return events


# ---- Step 6: 查詢層 ----

QUERY_KEYWORDS = {
    "fall": ["fall", "fell", "falling", "跌倒", "摔倒"],
    "normal_lying": ["lying down", "lie down", "rest", "sleep", "躺", "休息", "睡"],
    "standing": ["stand", "get up", "起身", "站"],
    "sitting": ["sit", "坐"],
}

def query_timeline(question, pose_timeline, fall_events):
    """
    簡單關鍵字比對：判斷query屬於哪個意圖類別，回傳對應的時間點清單。
    """
    q = question.lower()
    matched_intent = None
    for intent, keywords in QUERY_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            matched_intent = intent
            break

    if matched_intent is None:
        return f"Sorry, I couldn't understand the query: '{question}'"

    if matched_intent in ("fall", "normal_lying"):
        hits = [t for t, kind in fall_events if kind == matched_intent]
        label = "fall event(s)" if matched_intent == "fall" else "normal lying-down event(s)"
        if not hits:
            return f"No {label} found in this footage."
        times_str = ", ".join(f"{t}s" for t in hits)
        return f"Found {len(hits)} {label} at: {times_str}"
    else:
        hits = [t for t, pose in pose_timeline if pose == matched_intent]
        if not hits:
            return f"No '{matched_intent}' moments found."
        return f"Person was '{matched_intent}' at {len(hits)} sampled moments, e.g. around t={hits[0]}s to t={hits[-1]}s"


# ---- 執行demo ----

video_path = "../test_videos/normal_lying.mp4"
print(f"Analyzing: {video_path}\n")

raw_timeline = analyze_video(video_path, sample_fps=5)
filtered_timeline = mode_filter(raw_timeline, window=3)
events = detect_fall_events(filtered_timeline)

print("Detected events:", events)
print()

# 模擬家屬輸入自然語言查詢
test_queries = [
    "Did the person fall?",
    "When did they lie down normally?",
    "Did they stand up at any point?",
]

for q in test_queries:
    print(f"Q: {q}")
    print(f"A: {query_timeline(q, filtered_timeline, events)}\n")
