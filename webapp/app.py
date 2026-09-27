import os
import uuid
import subprocess
import threading
from collections import Counter

from flask import Flask, request, render_template, jsonify
import cv2
import torch
from ultralytics import YOLO
from transformers import AutoProcessor, OmDetTurboForObjectDetection
from PIL import Image

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "static", "outputs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

device = "cuda" if torch.cuda.is_available() else "cpu"

print("Loading pose model...")
pose_model = YOLO("yolov8n-pose.pt")

print("Loading OmDet-Turbo model...")
odt_model_id = "omlab/omdet-turbo-swin-tiny-hf"
odt_processor = AutoProcessor.from_pretrained(odt_model_id)
odt_model = OmDetTurboForObjectDetection.from_pretrained(odt_model_id).to(device)
print("Models loaded.")

# ---- Job tracking for async progress ----
jobs = {}
jobs_lock = threading.Lock()

TRACK_COLORS = ["#2383E2", "#8B5CF6", "#E67E22", "#0EA5A5", "#D6336C", "#7C3AED"]


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
    ratio = leg_height / torso_height
    return "standing" if ratio > 1.3 else "sitting"


def is_hand_near_face(keypoints, threshold_ratio=0.6):
    nose = keypoints[0]
    left_shoulder = keypoints[5]
    right_shoulder = keypoints[6]
    left_wrist = keypoints[9]
    right_wrist = keypoints[10]
    if nose[0] == 0 and nose[1] == 0:
        return False
    shoulder_width = abs(left_shoulder[0] - right_shoulder[0])
    if shoulder_width < 5:
        return False
    for wrist in (left_wrist, right_wrist):
        if wrist[0] == 0 and wrist[1] == 0:
            continue
        dist = ((wrist[0] - nose[0]) ** 2 + (wrist[1] - nose[1]) ** 2) ** 0.5
        if dist < shoulder_width * threshold_ratio:
            return True
    return False


def process_video(input_path, output_path, sample_fps=5, alert_duration_sec=2.0, progress_cb=None):
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError("Cannot open video")

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    width_px = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height_px = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_interval = max(1, int(native_fps / sample_fps))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, native_fps, (width_px, height_px))

    pose_history = []
    prev_pose = None
    entered_lying = False
    exit_lying_time = None
    current_pose_label = "detecting..."
    alert_text = None
    alert_until_time = -1

    events = []
    sampled_frames = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        timestamp = frame_idx / native_fps

        if frame_idx % frame_interval == 0:
            raw_frame_copy = frame.copy()
            results = pose_model(frame, verbose=False)
            hand_near_face = False
            if len(results[0].keypoints.xy) > 0:
                kpts = results[0].keypoints.xy[0].cpu().numpy()
                raw_pose = classify_pose(kpts)
                hand_near_face = is_hand_near_face(kpts)
            else:
                raw_pose = "no person detected"

            pose_history.append(raw_pose)
            if len(pose_history) > 5:
                pose_history.pop(0)
            current_pose_label = Counter(pose_history).most_common(1)[0][0]

            if current_pose_label == "lying on the floor":
                if not entered_lying:
                    entered_lying = True
                    if prev_pose == "standing":
                        alert_text = "FALL DETECTED"
                        alert_until_time = timestamp + alert_duration_sec
                        events.append({"time": round(timestamp, 2), "type": "fall"})
                    elif prev_pose == "sitting":
                        alert_text = "Normal lying down"
                        alert_until_time = timestamp + alert_duration_sec
                        events.append({"time": round(timestamp, 2), "type": "normal_lying"})
                exit_lying_time = None
            else:
                if entered_lying:
                    if exit_lying_time is None:
                        exit_lying_time = timestamp
                    elif timestamp - exit_lying_time >= 1.0:
                        entered_lying = False
                if current_pose_label in ("standing", "sitting"):
                    prev_pose = current_pose_label

            frame = results[0].plot()
            sampled_frames.append((round(timestamp, 2), raw_frame_copy, hand_near_face))

        cv2.putText(frame, f"Pose: {current_pose_label}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, f"t={timestamp:.1f}s", (20, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2, cv2.LINE_AA)

        if alert_text and timestamp <= alert_until_time:
            color = (0, 0, 255) if alert_text == "FALL DETECTED" else (0, 200, 0)
            cv2.putText(frame, alert_text, (20, height_px - 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3, cv2.LINE_AA)

        out.write(frame)
        frame_idx += 1

        if progress_cb and frame_idx % 10 == 0:
            progress_cb(min(frame_idx / total_frames, 1.0))

    cap.release()
    out.release()
    duration = frame_idx / native_fps

    temp_path = output_path.replace(".mp4", "_raw.mp4")
    os.rename(output_path, temp_path)
    subprocess.run([
        "ffmpeg", "-y", "-i", temp_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        output_path
    ], check=True)
    os.remove(temp_path)

    if progress_cb:
        progress_cb(1.0)

    return events, duration, sampled_frames


FALL_KEYWORDS = {
    "fall": ["fall", "fell", "falling", "跌倒", "摔倒"],
    "normal_lying": ["lying down", "lie down", "rest", "sleep", "躺", "休息", "睡"],
}
EATING_KEYWORDS = ["eat", "eating", "meal", "food", "吃飯", "吃東西", "用餐"]


def omdet_score_frame(frame_bgr, query_text):
    image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    inputs = odt_processor(image, text=[query_text], return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = odt_model(**inputs)
    results = odt_processor.post_process_grounded_object_detection(
        outputs, target_sizes=[image.size[::-1]], text_labels=[query_text],
        threshold=0.05, nms_threshold=0.3,
    )[0]
    if len(results["scores"]) == 0:
        return 0.0
    return float(results["scores"].max())


def merge_hits_to_intervals(scored, gap_threshold=600):
    if not scored:
        return []
    scored.sort(key=lambda x: x[0])
    intervals = []
    cur_start = scored[0][0]
    cur_end = scored[0][0]
    cur_max_score = scored[0][1]
    for t, score in scored[1:]:
        if t - cur_end <= gap_threshold:
            cur_end = t
            cur_max_score = max(cur_max_score, score)
        else:
            intervals.append({"start": cur_start, "end": cur_end, "max_score": round(cur_max_score, 3)})
            cur_start = t
            cur_end = t
            cur_max_score = score
    intervals.append({"start": cur_start, "end": cur_end, "max_score": round(cur_max_score, 3)})
    return intervals


def eating_search(sampled_frames, food_threshold=0.2, min_consecutive=1, gap_threshold=600, progress_cb=None):
    query = "a person eating food"
    frame_flags = []
    n = len(sampled_frames)
    for i, (t, frame, hand_near_face) in enumerate(sampled_frames):
        food_score = omdet_score_frame(frame, query)
        is_eating = (food_score >= food_threshold) and hand_near_face
        frame_flags.append((t, is_eating, food_score))
        if progress_cb and n:
            progress_cb((i + 1) / n)

    scored = []
    run_length = 0
    for t, is_eating, score in frame_flags:
        if is_eating:
            run_length += 1
            if run_length >= min_consecutive:
                scored.append((t, score))
        else:
            run_length = 0
    return merge_hits_to_intervals(scored, gap_threshold=gap_threshold)


def descriptive_search(query_text, sampled_frames, threshold=0.25, gap_threshold=5.0, progress_cb=None):
    clean_query = query_text.strip().rstrip("?!.").strip()
    scored = []
    n = len(sampled_frames)
    for i, (t, frame, _hand_near_face) in enumerate(sampled_frames):
        score = omdet_score_frame(frame, clean_query)
        if score >= threshold:
            scored.append((t, score))
        if progress_cb and n:
            progress_cb((i + 1) / n)
    return merge_hits_to_intervals(scored, gap_threshold=gap_threshold)


def set_progress(job_id, percent, stage):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["percent"] = round(percent, 1)
            jobs[job_id]["stage"] = stage


def run_job(job_id, input_path, output_path, raw_queries):
    try:
        def pose_progress(frac):
            set_progress(job_id, frac * 35, "Analyzing pose and motion…")

        events, duration, sampled_frames = process_video(
            input_path, output_path, progress_cb=pose_progress
        )
        set_progress(job_id, 35, "Pose analysis complete")

        combined_events = list(events)
        tracks = []
        answers = []

        # 過濾掉 fall/lying 相關字，剩下的才是要做描述式搜尋的查詢
        search_queries = []
        for q in raw_queries:
            q_lower = q.lower().strip()
            if not q_lower:
                continue
            matched_fall_intent = None
            for intent, keywords in FALL_KEYWORDS.items():
                if any(kw in q_lower for kw in keywords):
                    matched_fall_intent = intent
                    break
            if matched_fall_intent:
                hits = [e["time"] for e in events if e["type"] == matched_fall_intent]
                label = "fall event(s)" if matched_fall_intent == "fall" else "normal lying-down event(s)"
                if hits:
                    times_str = ", ".join(f"{t}s" for t in hits)
                    answers.append(f'"{q}" → Found {len(hits)} {label} at: {times_str}')
                else:
                    answers.append(f'"{q}" → No {label} found.')
            else:
                search_queries.append(q)

        n_search = max(len(search_queries), 1)
        remaining_budget = 65  # percent budget left after pose stage
        for idx, q in enumerate(search_queries):
            base = 35 + (remaining_budget / n_search) * idx
            span = remaining_budget / n_search

            def cb(frac, base=base, span=span, q=q):
                set_progress(job_id, base + frac * span, f'Searching: "{q}"…')

            q_lower = q.lower()
            if any(kw in q_lower for kw in EATING_KEYWORDS):
                intervals = eating_search(sampled_frames, progress_cb=cb)
                label = "eating"
            else:
                intervals = descriptive_search(q, sampled_frames, progress_cb=cb)
                label = q

            color = TRACK_COLORS[idx % len(TRACK_COLORS)]
            track_intervals = [{"start": iv["start"], "end": iv["end"], "score": iv["max_score"]} for iv in intervals]
            tracks.append({"label": label, "color": color, "intervals": track_intervals})

            if intervals:
                parts = []
                for iv in intervals:
                    if iv["end"] != iv["start"]:
                        parts.append(f"{iv['start']}s–{iv['end']}s (confidence {iv['max_score']})")
                    else:
                        parts.append(f"{iv['start']}s (confidence {iv['max_score']})")
                answers.append(f'"{label}" → Found during: ' + "; ".join(parts))
            else:
                answers.append(f'"{label}" → No matches found.')

        set_progress(job_id, 100, "Done")

        result = {
            "video_url": f"/static/outputs/{os.path.basename(output_path)}",
            "duration": duration,
            "events": combined_events,
            "tracks": tracks,
            "answer": "\n".join(answers) if answers else None,
        }

        with jobs_lock:
            jobs[job_id]["status"] = "done"
            jobs[job_id]["result"] = result

    except Exception as e:
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    if "video" not in request.files:
        return jsonify({"error": "No video file uploaded"}), 400

    video_file = request.files["video"]
    query_text = request.form.get("query", "").strip()
    raw_queries = [q.strip() for q in query_text.split(",") if q.strip()] if query_text else []

    job_id = uuid.uuid4().hex[:8]
    input_path = os.path.join(UPLOAD_DIR, f"{job_id}_{video_file.filename}")
    video_file.save(input_path)

    output_filename = f"{job_id}_annotated.mp4"
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    with jobs_lock:
        jobs[job_id] = {"status": "processing", "percent": 0, "stage": "Starting…"}

    thread = threading.Thread(target=run_job, args=(job_id, input_path, output_path, raw_queries))
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/progress/<job_id>")
def progress(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify({
            "status": job["status"],
            "percent": job.get("percent", 0),
            "stage": job.get("stage", ""),
        })


@app.route("/result/<job_id>")
def result(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job["status"] == "error":
            return jsonify({"error": job.get("error", "Unknown error")}), 500
        if job["status"] != "done":
            return jsonify({"error": "Job not finished"}), 400
        return jsonify(job["result"])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
