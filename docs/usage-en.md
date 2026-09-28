# Using CareTrace

Run the following in PowerShell from the project folder:

```powershell
.\scripts\start.ps1
```

Open **http://127.0.0.1:5000** and select **English** at the top right. Select **繁體中文** to switch back. The browser remembers your preference. Dialogs also include a language switch; unsaved fields, selected files, playback position and the current answer stay in place.

1. Select **Create resident**. Enter an alias, bed or room, and optional background.
2. Select **Add video**, choose a local MP4, MOV, WebM or AVI, and enter its actual recording start time. The limit is 512 MB and 15 minutes. Leave daily behavior analysis enabled to use OmDet alongside pose analysis.
3. Wait for analysis. If several tracks are detected, select those belonging to this resident. Hold Ctrl to select multiple tracks and verify them against the replay.
4. Use the **Evidence workspace** to replay skeleton evidence or the local original. Select colored timeline segments to seek directly to an event.
5. Ask questions such as “Are there any possible falls?”, “Are there any eating records?” or “Compare eating records this week and last week.” The date filter limits records; dates explicitly mentioned in the question take precedence.
6. Open **Manual review**, select a review result and save your notes. Excluded events are omitted from answers; the review history remains available.
7. Open **Care journal** to search records or **Export CSV**. Column headings, behavior names and review statuses use the selected language. Names and notes remain exactly as entered, with spreadsheet formula protection applied to CSV cells.
8. Use **Videos & data** to view or delete videos. Deleting a video also removes its evidence and related query records. Delete a resident's videos before deleting the resident.

Both languages use the same records, models and actions. Switching an existing answer translates its evidence-based text without submitting another model query. Dates in records are displayed in Taiwan time (UTC+8). JSON exports retain stable machine identifiers.

Models run locally and use existing pretrained weights; no training or API key is required. The first run may download models. A clearly labeled keyword fallback is used if the local language model is unavailable or its classification does not match explicit keywords.

Candidates need human review. Missing evidence does not establish that an event did not happen; model scores are not clinical probabilities. Eating candidates do not establish actual intake. Resident background is a reference for the caregiver, not an automated care decision.

For a new installation, run `scripts/setup.ps1` first. See [operations](operations.md) for configuration and [RTX 5090 notes](training-5090.md) for the existing training assessment.
