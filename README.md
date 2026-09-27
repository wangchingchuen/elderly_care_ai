# CareTrace — Elderly Care AI

影片姿態分析與事件查詢原型，使用 YOLO 姿態模型及 OmDet-Turbo，提供 Flask 網頁介面。

## 專案內容

- `webapp/app.py`：影片上傳、分析進度、事件查詢與結果 API。
- `webapp/templates/index.html`：網頁介面。
- `scripts/`：模型與影片分析的實驗腳本。

## 本機執行

需安裝 Python、FFmpeg（加入 PATH）及下列 Python 套件：

```sh
pip install flask opencv-python torch ultralytics transformers pillow requests
cd webapp
python app.py
```

瀏覽 `http://localhost:5000`。程式會載入 `yolov8n-pose.pt` 與 Hugging Face 上的 `omlab/omdet-turbo-swin-tiny-hf`，首次執行需要網路下載模型。

此處列出的是依程式匯入項目整理的依賴，尚未驗證相容套件版本或完整執行流程。

## 本機資料

測試照片、測試影片、使用者上傳內容、分析輸出及模型權重不納入 Git。執行實驗腳本前，請依腳本中的相對路徑準備本機測試資料，並從 `scripts` 目錄執行。
