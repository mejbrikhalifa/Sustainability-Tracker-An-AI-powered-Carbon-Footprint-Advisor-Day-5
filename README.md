# Sustainability Tracker: Day 5 🌍

Track your daily CO₂ emissions across Energy, Transport, and Meals. Get personalized eco-tips (GPT with fallback), view history and trends, and export beautiful PDF summaries with your branding.

Last updated: 2025-10-01

---

## Features

- **Dashboard** (Energy, Transport, Meals) with compact/comfy density
- **Personalized Eco Tips**
  - GPT-powered tips with resilient local fallback
  - Source badge (GPT vs Fallback)
- **History & Trends**
  - Per-category KPIs
  - 7-day change metrics, sparklines (in PDF)
- **Exports**
  - CSV downloads (Dashboard + History tab)
  - PDF export (server-side) with branding:
    - Title, logo (upload or fallback), accent color, text color, chart background
    - Optional pie chart and 7-day sparklines
    - Footer with &copy;/URL + page numbers
- **Demo Mode**
  - One-click demo values, “Exit Demo Mode” restore
  - Snapshot of pre-demo values and density + status indicator
  - “View snapshot detail” popover
- **Presets**
  - Prefill demo/presets safely (no widget state errors)
- **Robust UX**
  - Theme-aware defaults (light/dark)
  - Safe reruns (no deprecated APIs), no duplicate widget keys

---

## Quickstart

### Requirements

- Python 3.9+
- Pip packages:
  - streamlit
  - pandas
  - python-dotenv
  - openai (for GPT tips, optional)
  - reportlab (for PDF export)
  - matplotlib (optional, for PDF charts)

### Install

Using Anaconda (Windows)
```powershell
conda create -n sustain python=3.10 -y
conda activate sustain
pip install streamlit pandas python-dotenv openai reportlab matplotlib
```

Using pip (Windows PowerShell)
```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install streamlit pandas python-dotenv openai reportlab matplotlib
```

### Run

```powershell
streamlit run app.py
```

Streamlit will open at:
- Local URL: http://localhost:8501
- Network URL: http://<your-ip>:8501

---

## Environment & AI Tips

Set your OpenAI API key to enable GPT tips (optional). Without it, the app falls back to local tips automatically with a clear source badge.

Create a `.env` file in the project root:
```
OPENAI_API_KEY=sk-...
```

If you see 429 “insufficient_quota” errors:
- The app will retry and then use a local fallback tip.
- You can continue testing without GPT; the UI shows “AI source: Fallback”.

---

## Using the App

### Density & Layout
- Density toggle at the top: `Compact` (tight, best for PDF) or `Comfy`.
- “Reset layout” sets Compact and collapses expanders for better PDF export.

### Inputs
- Enter daily values in the three sections:
  - Energy: e.g., `electricity_kwh`, `natural_gas_m3`, `district_heating_kwh`...
  - Transport: `bus_km`, `train_km`, `petrol_liter`, etc.
  - Meals: `meat_kg`, `dairy_kg`, `vegetarian_kg`, etc.

### Calculate & Save
- Computes total emissions, KPIs, and saves to `history.csv`.
- CSV download buttons are uniquely keyed (no duplicate-widget errors).

### Eco Tips
- Generate a personalized tip based on today’s inputs.
- GPT-backed with fallback. Source badge shows “GPT” or “Fallback”.
- Copy-ready code blocks with built-in copy icon (no fragile JS).
- Summary and Tip are both shown as copyable code blocks and downloadable text.

### Demo Mode
- Toggle “Demo mode” in the header:
  - Forces Compact density on next run
  - Loads representative demo values
  - Auto-generates a tip
  - Shows snapshot capture time
  - “View snapshot detail” lets you inspect saved inputs
- “Exit Demo Mode” restores your previous values and density safely.

### Presets
- Prefill demos/presets via the “Prefill demos/presets” popover.
- Uses a “pending apply” mechanism to avoid Streamlit widget-state exceptions.

---

## PDF Export (Server-side)

Use the UI in the Eco Tips tab:
- “PDF Branding & Options” expander:
  - Title
  - Accent color (auto default by theme)
  - Text color (auto default by theme)
  - Chart background color (auto default by theme)
  - Include pie chart
  - Include 7-day sparklines
  - Margins (top/side/bottom)
  - Footer text and toggle
  - Logo upload (PNG/JPG). If none, fallback path check: `logo.png` in project root.
  - If no upload and no `logo.png`: a styled vector fallback badge (rounded rect “ST”) is drawn.
- Click “Generate Eco Tips PDF (beta)”, then the download button.

Dependencies:
- Required: `reportlab`
- Optional for charts: `matplotlib`

Install:
```powershell
pip install reportlab matplotlib
```

Note:
- The original “Export PDF tips” popover describes manual browser-based printing. The new server-side export produces a file directly.

---

## Files & Structure

- `app.py` — Main Streamlit app
  - Tabs: Dashboard, History, Breakdown, Tips
  - Demo mode, presets, density controls
  - CSV and PDF exports
  - AI source badge, copy-ready blocks
- `co2_engine.py` — Emissions engine
  - `CO2_FACTORS`, `calculate_co2()`, `calculate_co2_breakdown()`
- `utils.py` — Formatting, normalization, helper functions
  - `format_emissions()`, `percentage_change()`, `friendly_message()`, etc.
- `ai_tips.py` — GPT/local tips
  - `generate_tip()`; fallback-safe, retries
  - `LAST_TIP_SOURCE` to signal GPT vs Fallback
- `history.csv` — Saved user entries (auto-created)
- `logo.png` — Optional default logo for PDF
- `test_co2_engine.py`, `test_utils.py` — Sample tests

---

## Troubleshooting

- **DuplicateWidgetID**: Fixed by unique `key=` props on all download buttons.
- **StreamlitAPIException**: “cannot be modified after widget is instantiated”
  - We use pending state mechanisms (`_pending_values`, `_pending_density`, `_pending_demo_off`) and rerun before widgets build.
- **`st.experimental_rerun()` deprecated**
  - We use `st.rerun()` or avoid forced reruns with smooth success notices.
- **GPT quota errors (429)**
  - App retries and then falls back to local tips automatically.
- **Copy buttons “do nothing”**
  - Replaced with Streamlit code blocks. Use the built-in copy icon on the right.

---

## Testing

Run tests (if you add pytest):
```powershell
pip install pytest
pytest -q
```

---

## Changelog (2025-10-01)

- Added Demo Mode with snapshot, status, and “Exit Demo Mode” (safe).
- Fixed imports (use `co2_engine.calculate_co2` & local `get_yesterday_total`).
- Replaced all deprecated `st.experimental_rerun`.
- Unique `key` for download buttons to avoid DuplicateWidgetID.
- Reworked copy to built-in code-block copy icons.
- AI source badge (GPT vs Fallback).
- Server-side PDF export (ReportLab + optional Matplotlib):
  - Branding options and logo upload + fallback
  - Theme-aware defaults (accent, text, chart bg)
  - KPIs, summary, tip, per-category table, pie chart, per-activity table
  - 7-day sparklines per category
  - Footer (&copy;/URL + page numbers)
- Theme-aware colors and improved typography.

---

## License

MIT
