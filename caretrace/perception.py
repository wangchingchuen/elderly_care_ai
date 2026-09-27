"""Bounded-memory pretrained inference; timestamps are source-video seconds."""
import os
import math
import subprocess
import time
from collections import Counter, deque
from pathlib import Path

KINDS = {
    'standing': '站立', 'sitting': '坐姿', 'lying': '躺臥',
    'fall': '疑似跌倒', 'normal_lying': '坐姿轉躺臥', 'eating': '進食候選',
}
EDGES = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12),
         (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]


def classify_pose(points, confidence):
    import numpy as np
    valid = np.asarray(confidence) >= .35
    if sum(valid) < 7 or not all(valid[i] for i in (5, 6, 11, 12)):
        return 'uncertain'
    shoulder = (points[5] + points[6]) / 2
    hip = (points[11] + points[12]) / 2
    torso = hip - shoulder
    xs, ys = points[valid, 0], points[valid, 1]
    width, height = float(np.ptp(xs)), float(np.ptp(ys))
    if abs(torso[0]) > abs(torso[1]) * 1.2 or width / max(height, 1) > 1.15:
        return 'lying'
    if not all(valid[i] for i in (13, 14, 15, 16)):
        return 'uncertain'
    ankle = (points[15] + points[16]) / 2
    ratio = (ankle[1] - hip[1]) / max(abs(torso[1]), 1)
    angles = []
    for a, b, c in ((11, 13, 15), (12, 14, 16)):
        thigh, shin = points[a] - points[b], points[c] - points[b]
        cosine = np.dot(thigh, shin) / max(float(np.linalg.norm(thigh)*np.linalg.norm(shin)), 1)
        angles.append(float(np.degrees(np.arccos(np.clip(cosine, -1, 1)))))
    # Relative body proportions vary; straight knees are stronger evidence than
    # one fixed leg/torso ratio (which mislabels short-legged standing subjects).
    straight = min(angles) >= 160 and ratio >= .9
    return 'standing' if straight or ratio > 1.3 else 'sitting'


def hand_near_face(points, confidence):
    import numpy as np
    if confidence[0] < .35 or min(confidence[5], confidence[6]) < .35:
        return False
    width = max(float(np.linalg.norm(points[5] - points[6])), 1)
    return any(confidence[i] >= .35 and np.linalg.norm(points[i] - points[0]) < .85 * width for i in (9, 10))


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2-x1) * max(0, y2-y1)
    return inter / max(1, (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter)


class Tracker:
    """Conservative IoU tracks; identities are not resident identities."""
    def __init__(self):
        self.active = {}
        self.next_id = 1

    def update(self, boxes, timestamp):
        self.active = {k: v for k, v in self.active.items() if timestamp-v[1] < 1.5}
        available = set(self.active)
        result = []
        for box in boxes:
            best = max(available, key=lambda k: iou(box, self.active[k][0]), default=None)
            if best is None or iou(box, self.active[best][0]) < .15:
                best = self.next_id
                self.next_id += 1
            else:
                available.remove(best)
            self.active[best] = (box, timestamp)
            result.append(best)
        return result


class EventBuilder:
    def __init__(self, step):
        self.step = step
        self.tracks = {}
        self.events = []

    def add(self, track, t, pose, score, eating=False, food_score=0):
        state = self.tracks.setdefault(track, {'history': deque(maxlen=3), 'pose': None, 'last': t, 'open': {}})
        if t - state['last'] > self.step * 2.1:
            state['history'].clear()
            state['pose'] = None
            state['open'].clear()
        state['last'] = t
        state['history'].append(pose)
        # Unknown frames break state continuity; they must not bridge a fall transition.
        smooth = Counter(state['history']).most_common(1)[0][0] if pose != 'uncertain' else 'uncertain'
        old = state['pose']
        if smooth == 'lying' and old in ('standing', 'sitting'):
            self.events.append({'track_id': track, 'kind': 'fall' if old == 'standing' else 'normal_lying',
                                'start': t, 'end': t + self.step, 'score': score,
                                'signals': {'previous_pose': old, 'current_pose': smooth, 'method': 'pose_transition', 'warning': '需人工覆核；姿態轉換不等於確診跌倒'}})
        state['pose'] = smooth
        active = ([smooth] if smooth in ('standing', 'sitting', 'lying') else []) + (['eating'] if eating else [])
        for kind in list(state['open']):
            if kind not in active:
                del state['open'][kind]
        for kind in active:
            if kind not in state['open']:
                event = {'track_id': track, 'kind': kind, 'start': t, 'end': t + self.step,
                         'score': food_score if kind == 'eating' else score,
                         'signals': {'method': 'food_object_and_hand_near_face' if kind == 'eating' else 'pose_keypoints',
                                     'samples': 0}}
                self.events.append(event)
                state['open'][kind] = event
            event = state['open'][kind]
            event['end'] = t + self.step
            event['signals']['samples'] += 1

    def finish(self, duration):
        output = []
        for event in self.events:
            event['start'] = round(event['start'], 3)
            event['end'] = round(min(duration, event['end']), 3)
            event['score'] = round(float(event['score']), 3)
            # A fleeting hand/object coincidence must not become an eating event.
            minimum = max(2, math.ceil(1 / self.step)) if event['kind'] == 'eating' else 2
            if event['kind'] in ('fall', 'normal_lying') or event['signals']['samples'] >= minimum:
                if event['end'] > event['start']:
                    output.append(event)
        return output


class Analyzer:
    def __init__(self, root):
        self.root = Path(root)
        self.pose = self.odt = self.processor = None

    def _load(self, daily):
        import torch
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        self.device = os.getenv('CARETRACE_DEVICE', 'cuda' if torch.cuda.is_available() else 'cpu')
        if self.pose is None:
            from ultralytics import YOLO
            candidates = [self.root / 'webapp/yolov8n-pose.pt', self.root / 'scripts/yolov8n-pose.pt', self.root / 'data/models/yolov8n-pose.pt']
            weights = next((p for p in candidates if p.exists()), candidates[-1])
            weights.parent.mkdir(parents=True, exist_ok=True)
            self.pose = YOLO(str(weights))
        if daily and self.odt is None:
            from transformers import AutoProcessor, OmDetTurboForObjectDetection
            model_id = 'omlab/omdet-turbo-swin-tiny-hf'
            cache = str(self.root / 'data/models/hf')
            self.processor = AutoProcessor.from_pretrained(model_id, cache_dir=cache)
            self.odt = OmDetTurboForObjectDetection.from_pretrained(model_id, cache_dir=cache).to(self.device).eval()
            # Transformers 4.57 meta loading does not restore timm 1.0.24's
            # non-persistent Swin index/mask buffers. Recompute only geometry,
            # never reset_parameters() (which would overwrite learned weights).
            from timm.models.swin_transformer import WindowAttention, SwinTransformerBlock
            for module in self.odt.modules():
                if isinstance(module, (WindowAttention, SwinTransformerBlock)):
                    module._init_buffers()

    def objects(self, frame):
        import cv2
        import torch
        from PIL import Image
        labels = ['food', 'bowl', 'spoon', 'cup']
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        inputs = self.processor(images=image, text=labels, return_tensors='pt').to(self.device)
        with torch.inference_mode():
            outputs = self.odt(**inputs)
        result = self.processor.post_process_grounded_object_detection(
            outputs, target_sizes=[(image.height, image.width)], text_labels=labels,
            threshold=.2, nms_threshold=.3)[0]
        return [(box.tolist(), float(score)) for box, score in zip(result['boxes'].cpu(), result['scores'].cpu())]

    def analyze(self, source, target, daily, progress):
        import cv2
        import numpy as np
        import imageio_ffmpeg
        begin = time.monotonic()
        progress(2, '載入預訓練模型')
        cap = cv2.VideoCapture(str(source))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not cap.isOpened() or fps <= 0 or total <= 0:
            cap.release()
            raise ValueError('無法解碼影片，請使用有效的 MP4、MOV 或 WebM')
        duration = total / fps
        if duration > 900:
            cap.release()
            raise ValueError('單段影片上限為 15 分鐘，請先分段')
        try:
            self._load(daily)
        except Exception:
            cap.release()
            raise
        stride = max(1, round(fps / 5))
        sample_fps = fps / stride
        step = 1 / sample_fps
        builder, tracker = EventBuilder(step), Tracker()
        width, height = int(cap.get(3)), int(cap.get(4))
        scale = min(1, 960 / max(width, height))
        out_w, out_h = int(width*scale)//2*2, int(height*scale)//2*2
        raw = Path(target).with_suffix('.raw.mp4')
        writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*'mp4v'), sample_fps, (out_w, out_h))
        if not writer.isOpened():
            cap.release()
            raise RuntimeError('無法建立骨架影片')
        index = samples = 0
        seen_tracks = {}
        try:
            while True:
                ok = cap.grab()
                if not ok:
                    break
                if index % stride:
                    index += 1
                    continue
                ok, frame = cap.retrieve()
                if not ok:
                    raise ValueError('影片解碼中斷')
                t = index / fps
                frame = cv2.resize(frame, (out_w, out_h))
                result = self.pose.predict(frame, conf=.35, imgsz=640, device=self.device, verbose=False)[0]
                canvas = np.full((out_h, out_w, 3), (34, 30, 22), dtype=np.uint8)
                boxes = result.boxes.xyxy.cpu().numpy().tolist()
                identities = tracker.update(boxes, t)
                # Only run object detection when a hand signal is present.
                keypoints = result.keypoints.xy.cpu().numpy() if len(boxes) else []
                scores = result.keypoints.conf.cpu().numpy() if len(boxes) else []
                hands = [hand_near_face(p, c) for p, c in zip(keypoints, scores)]
                objects = self.objects(frame) if daily and any(hands) else []
                for track, box, points, conf, hand in zip(identities, boxes, keypoints, scores, hands):
                    pose = classify_pose(points, conf)
                    # Object center must be inside this person's box, not another resident's scene.
                    food = max((s for b, s in objects if box[0] <= (b[0]+b[2])/2 <= box[2] and box[1] <= (b[1]+b[3])/2 <= box[3]), default=0)
                    builder.add(track, t, pose, float(np.mean(conf[conf >= .35])) if any(conf >= .35) else 0,
                                eating=hand and food >= .2, food_score=food)
                    seen_tracks[track] = seen_tracks.get(track, 0) + 1
                    color = [(135, 212, 65), (225, 164, 87), (115, 143, 234)][(track-1) % 3]
                    for a, b in EDGES:
                        if min(conf[a], conf[b]) >= .35:
                            cv2.line(canvas, tuple(points[a].astype(int)), tuple(points[b].astype(int)), color, 2, cv2.LINE_AA)
                    for p, c in zip(points, conf):
                        if c >= .35:
                            cv2.circle(canvas, tuple(p.astype(int)), 3, (235, 241, 237), -1, cv2.LINE_AA)
                    cv2.putText(canvas, f'Track {track}: {pose}', (max(0, int(box[0])), max(45, int(box[1])-10)), cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1, cv2.LINE_AA)
                cv2.putText(canvas, f'CareTrace | skeleton evidence | {t:.1f}s', (14, 24), cv2.FONT_HERSHEY_SIMPLEX, .5, (215, 220, 210), 1, cv2.LINE_AA)
                writer.write(canvas)
                samples += 1
                progress(min(92, 5 + 87*index/total), f'分析骨架與行為 · {t:.1f} / {duration:.1f} 秒')
                index += 1
        finally:
            cap.release()
            writer.release()
        if not samples:
            raise ValueError('影片沒有可分析的影格')
        progress(95, '製作可回看的骨架證據')
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-i', str(raw), '-an',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target)],
                       check=True, capture_output=True, timeout=180)
        raw.unlink(missing_ok=True)
        return {'duration': duration, 'events': builder.finish(duration), 'details': {
            'tracks': [{'id': k, 'samples': v} for k, v in seen_tracks.items()],
            'sample_fps': sample_fps, 'samples': samples, 'elapsed_seconds': round(time.monotonic()-begin, 2),
            'device': self.device, 'pose_model': 'yolov8n-pose', 'daily_model': 'omdet-turbo-swin-tiny-hf' if daily else None,
            'note': '模型分數並非行為正確機率；未偵測不代表未發生。追蹤代號需人工對應住民。'}}
