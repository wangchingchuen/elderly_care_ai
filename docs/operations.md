# Local operation

## Start and use

1. Run `scripts/start.ps1` and open `http://127.0.0.1:5000`.
2. Create a resident code and optional care background. Real names are not required.
3. Upload one of your local videos, assign its resident and actual recording start time. Keep daily analysis enabled for food/object evidence.
4. Wait for completion. The first analysis downloads public model weights if not cached; later processing is local.
5. Review the skeleton. If multiple track IDs are shown, explicitly select only those belonging to the resident. Ctrl-click selects multiple fragments on Windows. The system does not recognize resident identity automatically.
6. Ask a question in Chinese or English. Date examples: `今天有進食紀錄嗎？`, `2026-09-28 有疑似跌倒嗎？`, `這週和上週的进食紀錄比較`, `When was the person sitting?`.
7. Click an evidence card or timeline segment. Confirm, reject or annotate the event based on the actual evidence.
8. Export the selected resident/date range from the journal. Data-management deletion removes the local source and derived records together.

Queries use the selected resident. Change the resident selector to query someone else. The LLM does not infer person identity from a name inside arbitrary question text. The selected date filter persists across views; explicit dates / today / yesterday / week expressions in a question override it for that query.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| First analysis is slow | Wait for pretrained weights to download. CPU behavior analysis may take longer than the video duration. |
| A job failed | Read its error in the evidence workspace, resolve missing model/network/codec issues and retry. Failed jobs do not produce fabricated records. |
| Service stopped during analysis | Restart, open the interrupted video, select retry. Completed records remain available. |
| No events in the journal | Check selected resident/date, whether analysis finished, and whether the resident's track IDs were assigned. |
| Query says keyword fallback | The local LLM could not load or returned an invalid/disagreeing plan. The UI labels this mode. Recheck model availability; basic deterministic queries still work. |
| No eating results | Hands may be occluded or food not associated with the tracked person. Absence of a candidate does not prove absence of eating. |
| Original video cannot play | Some source codecs are unsupported by browsers. Use the generated H.264 skeleton MP4 or convert a copy of the original. |
| Cannot delete a video | Wait for queued/active analysis to finish. Deletion is blocked while the worker owns the video. |

## Configuration

Environment variables are optional; no API key is required.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CARETRACE_DATA_DIR` | project `data/` | SQLite and uploaded/evidence media directory |
| `CARETRACE_PORT` | `5000` | Local HTTP port |
| `CARETRACE_DEVICE` | `cuda` when available, otherwise `cpu` | Perception inference device |
| `CARETRACE_LLM_MODEL` | `Qwen/Qwen3-0.6B` | Local Transformers-compatible query model |
| `CARETRACE_DISABLE_LLM` | unset | `1` enables explicitly labeled keyword-only mode |

Model cache lives under `data/models/hf`; an existing user cache may be reused for Qwen. YOLO uses a local `webapp/yolov8n-pose.pt` or `scripts/yolov8n-pose.pt` if available, otherwise downloads to `data/models/`. Keep these files for offline use. `HF_HUB_OFFLINE=1` prevents model metadata network requests once all required files are cached.

## Backup and deletion

Stop the server before copying the entire configured data directory. SQLite and its media must be backed up together. The public Git repository is not a backup of private care records. Existing experimental files under `test_videos/`, `test_photos/`, `outputs/` and the old `webapp/uploads/` are not imported automatically or deleted by the new application.

Deleting a record removes application files, not external backups or the original source file you uploaded from. Stop the service before a database restore. Version 1 is a single-user local deployment; keep one process per data directory.
