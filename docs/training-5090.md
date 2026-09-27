# RTX 5090 and future training

This release uses existing pretrained YOLOv8n-Pose, OmDet-Turbo and Qwen models. No training was performed and no care footage was uploaded to a training service.

## Can an RTX 5090 train this project's models?

YOLOv8 pose supports fine-tuning, and a 5090 can be a suitable training device when the CUDA software stack supports its Blackwell architecture. PyTorch introduced Blackwell / CUDA 12.8 support in 2.7. The official previous-versions page includes Windows CUDA 12.8 wheels for PyTorch 2.7.1 and torchvision 0.22.1:

- [PyTorch 2.7 announcement](https://pytorch.org/blog/pytorch-2-7/)
- [Official Windows / Linux installation matrix](https://pytorch.org/get-started/previous-versions/)
- [YOLOv8 model support](https://docs.ultralytics.com/models/yolov8/)

The environment used for this release exposes CPU-only PyTorch. No 5090 throughput, VRAM limit, training run or accuracy gain has been measured. The included GPU check executes a small forward/backward calculation, not a model training run.

On the machine with the 5090, use a current NVIDIA driver and run:

```powershell
.\scripts\setup.ps1 -Cuda128
.\.venv\Scripts\python.exe scripts\check_gpu.py
```

Verify the reported GPU name, CUDA availability and `forward_backward: passed`. Do not infer success just from the CUDA version printed by a driver utility. The application automatically selects CUDA for YOLO/OmDet when available; the small query LLM defaults to CPU to leave GPU memory for perception.

## Which data would training require?

| Desired improvement | Required evidence / labels | Recommendation |
| --- | --- | --- |
| Better body keypoints | Person boxes and 17 keypoints with visibility labels | Public COCO-Pose is available, but the pretrained model already learned general human poses |
| More reliable fall detection | Video-level temporal labels, falls and hard negatives such as sitting, bending, kneeling and normal lying | An action/temporal model or improved rules may help more than retraining YOLO |
| Better eating verification | Time intervals, hand/object association and non-eating lookalikes | Current hand + food-object logic remains a candidate detector |
| Real facility robustness | Consented footage from different people, rooms, cameras, lighting and occlusion conditions | Collect and label only if the real deployment justifies it |

[COCO-Pose documentation](https://docs.ultralytics.com/datasets/pose/coco/) describes the publicly available keypoint format. Its small COCO8-Pose subset is a pipeline smoke-test dataset, not evidence of real-world improvement.

Do not split adjacent frames from the same recording across train and test sets. Split by person, recording and preferably location; retain an untouched test set and report misses and false positives as well as average accuracy. Public availability does not establish permission for every intended use; retain source license information when data is actually acquired.

## Decision for this version

Skip training. Existing models are sufficient to run the complete application and generate inspectable candidates. The supplied four clips are useful for functional checks and qualitative inspection, but are not a labeled, diverse training/evaluation dataset. They cannot establish a reliable care-monitoring accuracy rate.

The initial standing/sitting error was addressed by adding knee-angle information to the temporal pipeline. The model loading failure was fixed as a dependency compatibility issue. Neither needed YOLO retraining. More robust occlusion handling and behavior validation remain future evaluation work.
