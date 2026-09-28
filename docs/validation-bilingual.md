# CareTrace v0.2.0 bilingual acceptance

Date: 2026-09-28, Windows, Python 3.10, CPU inference. No training was performed.

The existing baseline was pushed and verified on `origin/main` at `5a65893` before implementation. The bilingual implementation uses `feature/bilingual-interface`.

| Check | Result |
| --- | --- |
| Backend regression and locale semantics | 24 pytest tests passed |
| TypeScript and production build | Passed |
| Shared catalog, placeholder parity, JSX coverage, worker errors, storage-disabled behavior | `npm run test:i18n` passed |
| Real Chinese Chromium workflow | 13 acceptance checks passed; no JavaScript page errors |
| Real English Chromium workflow | Same 13 checks passed; no JavaScript page errors |
| Real local Qwen planning | 12 Chinese/English cases classified as expected in `local_llm` mode |
| Running v0.2.0 smoke check | Language switching, persisted preference, 1440/834/390 px layouts and final English stats layout passed |

Both browser runs used actual YOLO and OmDet analysis of a local video, followed by local LLM queries. They exercised resident creation, file upload, manual multi-track assignment, skeleton playback and seeking, evidence navigation, review persistence, localized CSV export, service restart and deletion, plus visible errors for corrupt video.

Switching languages retained unsaved resident fields, selected upload files, recording time, review status and notes, typed questions, current answers and playback position. Existing answers switched between translations of the same evidence. Reload preserved the selected locale. The English run checked visible text and accessible labels for untranslated Chinese, excluding the intentionally Chinese language-switch label. Test resident names and notes used English; separate API tests verified that Chinese user data remained unchanged in English exports.

Local reports (ignored by Git):

- English: `artifacts/e2e-cee38402/report.json`
- Chinese: `artifacts/e2e-1b225be2/report.json`
- Final model-plan checks: `artifacts/bilingual-query-plans.json`

The first English run exposed a model classification mismatch; explicit bilingual planning examples resolved it. A subsequent unsupported-intake question exposed invalid model output; an unsupported example resolved that case. Keyword fallback remains available and explicitly labeled for other model failures. The final planning suite was rerun after these prompt changes; the final running-service smoke check followed the layout correction and version update.

To reproduce:

```powershell
.\.venv\Scripts\python.exe -m pytest
npm.cmd --prefix frontend run test:i18n
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -X utf8 scripts/e2e.py --language zh-TW
.\.venv\Scripts\python.exe -X utf8 scripts/e2e.py --language en
.\.venv\Scripts\python.exe -X utf8 scripts/validate_queries.py
```

Browser/model checks require local model weights, Playwright Chromium and the ignored sample video `test_videos/fall_event.mp4`. CI runs backend tests, the frontend build and catalog checks without private media or model inference. These checks establish application workflow parity, not clinical accuracy or general model reliability.
