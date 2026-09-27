"""Check the actual CUDA stack without downloading data or starting training."""
import json
import torch

report = {'torch': torch.__version__, 'cuda_build': torch.version.cuda, 'cuda_available': torch.cuda.is_available()}
if torch.cuda.is_available():
    report.update(device=torch.cuda.get_device_name(0), capability=torch.cuda.get_device_capability(0),
                  vram_gib=round(torch.cuda.get_device_properties(0).total_memory/1024**3, 1))
    try:
        x = torch.randn((1024, 1024), device='cuda', requires_grad=True)
        (x @ x.T).mean().backward()
        torch.cuda.synchronize()
        report['forward_backward'] = 'passed'
    except Exception as exc:
        report['forward_backward'] = repr(exc)
else:
    report['forward_backward'] = 'not run; CPU-only environment or no accessible CUDA device'
print(json.dumps(report, ensure_ascii=False, indent=2))
