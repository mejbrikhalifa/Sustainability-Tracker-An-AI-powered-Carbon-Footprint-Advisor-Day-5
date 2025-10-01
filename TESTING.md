# Day 5 – UI Validation Checklist

Use this checklist to validate the Streamlit app end-to-end for your Day 5 submission.

## How to Run

- Install dependencies: `pip install -r requirements.txt`
- Launch the app: `streamlit run app.py`
- Optional: Set your API key in `.env` (see README → Secrets)
- Optional: Enable Debug (performance) in the header to adjust spinner threshold and enable perf logging

## Checklist

| Area | Step | Expected | Status | Notes |
|---|---|---|---|---|
| End-to-End | Enter inputs on Dashboard, click “Calculate & Save” | KPIs update; Trend line and mini sparklines reflect new entry | ☐ |  |
| End-to-End | Verify category table and bar chart | Values match inputs and emission factors | ☐ |  |
| Eco Tips | Open “💡 Eco Tips”, click “Generate Eco Tip” | Spinner shows only if > threshold; tip appears with icon; elapsed time shown | ☐ |  |
| Eco Tips | Header shows dominant icon and caption | “Dominant today: Transport/Energy/Meals” correct | ☐ |  |
| Eco Tips | Summary shows colored tags and backend metric | Tags match inputs; “Today’s total (backend)” equals Dashboard total | ☐ |  |
| Eco Tips | “Last generated tip” persists across tab switch/rerun | Prior tip with icon visible | ☐ |  |
| Presets | Use “Vegetarian day”, then Calculate & Save | Inputs populate; charts/KPIs update | ☐ |  |
| Presets | Use “No car day”, then Calculate & Save | Transport minimized; charts/KPIs update | ☐ |  |
| Presets | “✨ Load Demo User” in Eco Tips | Inputs auto-fill; tip auto-generates with spinner if slow | ☐ |  |
| Summary Actions | Click “📋 Copy Summary” and paste elsewhere | Plain text summary matches UI | ☐ |  |
| Summary Actions | “⬇️ Download summary (.txt)” and open | File content matches summary | ☐ |  |
| PDF Export | Export PDF (Dashboard/Eco Tips) in Compact | Tip text included; layout clean; KPIs/charts readable | ☐ |  |
| Perf Logging | Enable Debug logging; generate tip | perf_log.csv gains new row (timestamp, elapsed_s, emissions_kg) | ☐ |  |
| Fallback | Remove/rename `.env`; generate tip | Fallback tip appears; UI stable | ☐ |  |
| Edge Cases | All zeros; generate tip | Summary says “No activities logged yet.”; tip generated or friendly warning shown | ☐ |  |
| Edge Cases | Very large inputs (stress) | No layout break; tip generated; elapsed time recorded | ☐ |  |

## Point 6 – User Interface Testing

### 1) Density Toggle Testing
- Locate the Density toggle in the header.
- Switch between Compact and Comfy modes.
- Verify:
  - Compact = tighter spacing, minimal padding.
  - Comfy = more spacing, easy readability.
  - KPIs, charts, expanders, and summaries remain readable; no overlapping widgets.

### 2) PDF Export Testing
- Set Density to Compact.
- Collapse unnecessary expanders.
- Use the Export PDF tips guidance in the header.
- Open the exported PDF and verify:
  - Charts, KPIs, summary, and eco tips are visible and readable.
  - Layout matches the on‑screen Compact view; nothing is cut off.

### 3) Preset Testing
- On Dashboard:
  - Click “Vegetarian day” preset → Calculate & Save.
  - Confirm inputs reflect meal‑heavy day; transport/energy minimal.
- Go to Eco Tips tab:
  - Click Generate Eco Tip.
  - Tip reflects vegetarian‑focused activities.
  - Icon and summary update correctly.
- Repeat for “No car day” preset → Calculate & Save.
  - Transport minimized.
  - Eco Tip reflects non‑transport emphasis.

### Validation Checklist (Point 6)

| Step | Expected Result | Status | Notes |
|---|---|---|---|
| Switch Density toggle | Layout adjusts correctly (Compact/Comfy) | ☐ |  |
| Export PDF in Compact mode | Layout readable, charts included | ☐ |  |
| Vegetarian day preset | Inputs correct, tip matches meals | ☐ |  |
| No car day preset | Inputs correct, tip matches transport | ☐ |  |

## Notes

- Best PDF results with Compact density and collapsed expanders.
- When experimenting with API behavior, keep the terminal open to see retry/backoff prints.
- Validation: app shows inline category warnings and per-field tooltips; Save/Generate are guarded with friendly messages.
