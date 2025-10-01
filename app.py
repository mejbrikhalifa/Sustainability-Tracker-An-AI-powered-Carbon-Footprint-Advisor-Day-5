# app.py
import os
import pandas as pd
import datetime as dt
import streamlit as st
import io
from co2_engine import calculate_co2, CO2_FACTORS, calculate_co2_breakdown
from utils import (
    format_emissions as fmt_emissions,
    friendly_message as status_message,
    percentage_change,
)
from ai_tips import generate_tip, LAST_TIP_SOURCE
import time
import concurrent.futures
import csv

# Set page config first (must be the first Streamlit command)
st.set_page_config(page_title="Sustainability Tracker", page_icon="🌍", layout="wide")

# =========================
# Category Mapping & Storage
# =========================
CATEGORY_MAP = {
    "Energy": [
        "electricity_kwh",
        "natural_gas_m3",
        "hot_water_liter",
        "cold_water_liter",
        "district_heating_kwh",
        "propane_liter",
        "fuel_oil_liter",
    ],
    "Transport": [
        "petrol_liter",
        "diesel_liter",
        "bus_km",
        "train_km",
        "bicycle_km",
        "flight_short_km",
        "flight_long_km",
    ],
    "Meals": [
        "meat_kg",
        "chicken_kg",
        "eggs_kg",
        "dairy_kg",
        "vegetarian_kg",
        "vegan_kg",
    ],
}
ALL_KEYS = [k for keys in CATEGORY_MAP.values() for k in keys]

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.csv")


# =========================
# Helper Functions
# =========================
def compute_category_emissions(activity_data: dict) -> dict:
    result = {}
    for cat, keys in CATEGORY_MAP.items():
        subtotal = 0.0
        for k in keys:
            amt = float(activity_data.get(k, 0) or 0)
            factor = CO2_FACTORS.get(k)
            if factor is not None:
                subtotal += amt * factor
        result[cat] = round(subtotal, 2)
    return result


def load_history() -> pd.DataFrame:
    if os.path.exists(HISTORY_FILE):
        try:
            df = pd.read_csv(HISTORY_FILE, parse_dates=["date"])
            return df
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def save_entry(date_val: dt.date, activity_data: dict, total: float):
    df = load_history()
    row = {"date": pd.to_datetime(date_val)}
    for k in ALL_KEYS:
        row[k] = float(activity_data.get(k, 0) or 0)
    row["total_kg"] = float(total)

    if df.empty:
        df = pd.DataFrame([row])
    else:
        mask = df["date"].dt.date == date_val
        if mask.any():
            # Upsert
            df.loc[mask, list(row.keys())] = list(row.values())
        else:
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)

    df = df.sort_values("date")
    df.to_csv(HISTORY_FILE, index=False)


def get_yesterday_total(df: pd.DataFrame, date_val: dt.date) -> float:
    if df.empty:
        return 0.0
    yesterday = pd.to_datetime(date_val) - pd.Timedelta(days=1)
    mask = df["date"].dt.date == yesterday.date()
    if mask.any():
        return float(df.loc[mask, "total_kg"].iloc[0])
    return 0.0


def compute_streak(df: pd.DataFrame, date_val: dt.date) -> int:
    """Compute the current streak of consecutive days up to date_val."""
    if df.empty:
        return 0

    # Ensure all dates are datetime.date
    df_dates = df["date"].dt.date if pd.api.types.is_datetime64_any_dtype(df["date"]) else df["date"]
    dayset = set(df_dates)

    streak = 0
    current = date_val
    while current in dayset:
        streak += 1
        current -= dt.timedelta(days=1)

    return streak


def award_badges(today_total: float, streak: int, df: pd.DataFrame) -> list:
    badges = []
    if not df.empty:
        badges.append("📅 Consistency: Entries logged!")
    if today_total < 20:
        badges.append("🌿 Low Impact Day (< 20 kg)")
    if streak >= 3:
        badges.append("🔥 3-Day Streak")
    if streak >= 7:
        badges.append("🏆 7-Day Streak")
    if not df.empty:
        recent = df.tail(7)
        avg7 = float(recent["total_kg"].mean()) if not recent.empty else 0.0
        if avg7 and today_total < 0.9 * avg7:
            badges.append("📈 10% Better than 7-day avg")
    return badges


# =========================
# Helper formatters
# =========================
def format_summary(user_data: dict) -> str:
    """Return a compact, human-friendly summary of today's inputs.
    Only include fields that are present and > 0 where numeric.
    """
    parts: list[str] = []
    def _num(v):
        try:
            return float(v)
        except Exception:
            return v

    # Transport
    if (val := _num(user_data.get("petrol_liter"))) and isinstance(val, float) and val > 0:
        parts.append(f"🚗 Petrol: {val:.1f} L")
    if (val := _num(user_data.get("diesel_liter"))) and isinstance(val, float) and val > 0:
        parts.append(f"🚙 Diesel: {val:.1f} L")
    if (val := _num(user_data.get("bus_km"))) and isinstance(val, float) and val > 0:
        parts.append(f"🚌 Bus: {val:.0f} km")
    if (val := _num(user_data.get("train_km"))) and isinstance(val, float) and val > 0:
        parts.append(f"🚆 Train: {val:.0f} km")
    if (val := _num(user_data.get("bicycle_km"))) and isinstance(val, float) and val > 0:
        parts.append(f"🚴 Bike: {val:.0f} km")

    # Energy
    if (val := _num(user_data.get("electricity_kwh"))) and isinstance(val, float) and val > 0:
        parts.append(f"⚡ Electricity: {val:.1f} kWh")
    if (val := _num(user_data.get("district_heating_kwh"))) and isinstance(val, float) and val > 0:
        parts.append(f"🔥 District heat: {val:.1f} kWh")
    if (val := _num(user_data.get("natural_gas_m3"))) and isinstance(val, float) and val > 0:
        parts.append(f"🏠 Gas: {val:.1f} m³")
    if (val := _num(user_data.get("hot_water_liter"))) and isinstance(val, float) and val > 0:
        parts.append(f"🚿 Hot water: {val:.0f} L")

    # Meals
    meal_bits = []
    for key, label in [
        ("meat_kg", "🥩 Meat"),
        ("chicken_kg", "🍗 Chicken"),
        ("dairy_kg", "🥛 Dairy"),
        ("eggs_kg", "🥚 Eggs"),
        ("vegetarian_kg", "🥗 Veg"),
        ("vegan_kg", "🌱 Vegan"),
    ]:
        val = _num(user_data.get(key))
        if isinstance(val, float) and val > 0:
            meal_bits.append(f"{label}: {val:.2f} kg")
    if meal_bits:
        parts.append(" | ".join(meal_bits))

    return " | ".join(parts) if parts else "No activities logged yet."


def format_summary_html(user_data: dict) -> str:
    """Return an HTML-formatted summary with colored tags. Safe for st.markdown(..., unsafe_allow_html=True)."""
    # Color groups
    def tag(label: str, color: str) -> str:
        return (
            f"<span style='display:inline-block;margin:2px 6px 2px 0;padding:2px 8px;"
            f"border-radius:12px;background:{color};color:#112;border:1px solid rgba(0,0,0,0.1);font-size:0.92em;'>"
            f"{label}</span>"
        )
    html_parts: list[str] = []
    # Transport (green-ish)
    trans_color = "#e6f4ea"  # light green
    for key, icon, unit, fmt in [
        ("petrol_liter", "🚗 Petrol", "L", "{:.1f}"),
        ("diesel_liter", "🚙 Diesel", "L", "{:.1f}"),
        ("bus_km", "🚌 Bus", "km", "{:.0f}"),
        ("train_km", "🚆 Train", "km", "{:.0f}"),
        ("bicycle_km", "🚴 Bike", "km", "{:.0f}"),
    ]:
        val = user_data.get(key)
        try:
            fv = float(val)
        except Exception:
            fv = 0.0
        if fv > 0:
            html_parts.append(tag(f"{icon}: {fmt.format(fv)} {unit}", trans_color))

    # Energy (blue-ish)
    energy_color = "#e8f0fe"  # light blue
    for key, icon, unit, fmt in [
        ("electricity_kwh", "⚡ Electricity", "kWh", "{:.1f}"),
        ("district_heating_kwh", "🔥 District heat", "kWh", "{:.1f}"),
        ("natural_gas_m3", "🏠 Gas", "m³", "{:.1f}"),
        ("hot_water_liter", "🚿 Hot water", "L", "{:.0f}"),
    ]:
        val = user_data.get(key)
        try:
            fv = float(val)
        except Exception:
            fv = 0.0
        if fv > 0:
            html_parts.append(tag(f"{icon}: {fmt.format(fv)} {unit}", energy_color))

    # Meals (orange-ish)
    meal_color = "#fff4e5"  # light orange
    for key, icon in [
        ("meat_kg", "🥩 Meat"),
        ("chicken_kg", "🍗 Chicken"),
        ("dairy_kg", "🥛 Dairy"),
        ("eggs_kg", "🥚 Eggs"),
        ("vegetarian_kg", "🥗 Veg"),
        ("vegan_kg", "🌱 Vegan"),
    ]:
        val = user_data.get(key)
        try:
            fv = float(val)
        except Exception:
            fv = 0.0
        if fv > 0:
            html_parts.append(tag(f"{icon}: {fv:.2f} kg", meal_color))

    if not html_parts:
        return "<em>No activities logged yet.</em>"
    return "\n".join(html_parts)


def dominant_category_icon(user_data: dict) -> tuple[str, str]:
    """Return (icon, category_label) for the dominant emitting category.
    Defaults to neutral if nothing is logged.
    """
    try:
        cat = compute_category_emissions(user_data)
    except Exception:
        cat = {}
    if not cat:
        return ("💡", "Tip")
    dom = max(cat.items(), key=lambda x: x[1])[0]
    icon_map = {"Energy": "⚡", "Transport": "🚗", "Meals": "🥗"}
    return (icon_map.get(dom, "💡"), dom)


# =========================
# Validation helpers
# =========================
def _coerce_float(v):
    try:
        return float(v)
    except Exception:
        return None

def has_meaningful_input(user_data: dict) -> bool:
    """True if at least one numeric input is > 0."""
    for v in user_data.values():
        fv = _coerce_float(v)
        if fv is not None and fv > 0:
            return True
    return False

def find_invalid_fields(user_data: dict) -> list[str]:
    """Return keys that are negative or non-numeric when a number is expected."""
    bad = []
    for k, v in user_data.items():
        fv = _coerce_float(v)
        if fv is None:
            bad.append(k)
        elif fv < 0:
            bad.append(k)
    return bad

def show_input_warnings(user_data: dict):
    """Render inline warnings grouped by category for any invalid fields.
    This is shown immediately after inputs so users can correct quickly.
    """
    invalid = find_invalid_fields(user_data)
    if not invalid:
        return
    # Group invalid keys by category using CATEGORY_MAP
    grouped = {cat: [] for cat in CATEGORY_MAP.keys()}
    for cat, keys in CATEGORY_MAP.items():
        grouped[cat] = [k for k in invalid if k in keys]
    # Render per-category messages if any
    has_any = any(grouped[cat] for cat in grouped)
    if has_any:
        st.markdown("<div style='color:#b00020;font-weight:600;'>Input issues detected:</div>", unsafe_allow_html=True)
        for cat in ["Energy", "Transport", "Meals"]:
            if grouped.get(cat):
                issues = ", ".join(grouped[cat])
                st.markdown(f"- <span style='color:#b00020;'>[{cat}] Invalid: {issues}</span>", unsafe_allow_html=True)

def should_generate_tip(user_data: dict) -> bool:
    """Pure decision helper: return True if inputs are valid and meaningful.
    This is used by the UI layer and covered by unit tests.
    """
    invalid = find_invalid_fields(user_data)
    if invalid:
        return False
    return has_meaningful_input(user_data)

# =========================
# Streamlit App
# =========================
def main():
    # Density + header
    # Initialize persisted UI density in session state
    if "density" not in st.session_state:
        st.session_state["density"] = "Compact"

    # Read density from URL query params if present (new API)
    try:
        qp_density = st.query_params.get("density")
        if qp_density in ("Compact", "Comfy") and qp_density != st.session_state["density"]:
            st.session_state["_pending_density"] = qp_density
    except Exception:
        pass

    # Density toggle: Compact vs Comfy
    def _apply_pending_density_if_any():
        """Apply queued density (Compact/Comfy) before the density radio is instantiated."""
        pdn = st.session_state.get("_pending_density")
        if isinstance(pdn, str) and pdn:
            st.session_state["density"] = pdn
            st.session_state.pop("_pending_density", None)

    def _apply_pending_demo_toggle_if_any():
        """Apply a queued request to turn demo_mode off before the checkbox exists."""
        if st.session_state.get("_pending_demo_off"):
            # Safely set the widget-bound key before checkbox is created in this run
            st.session_state["demo_mode"] = False
            st.session_state.pop("_pending_demo_off", None)

    _apply_pending_density_if_any()
    _apply_pending_demo_toggle_if_any()

    dens_col1, dens_col2 = st.columns([3, 1])
    with dens_col1:
        st.title("Sustainability Tracker 🌍")
        st.caption("Track daily CO₂ emissions and get actionable tips")
    with dens_col2:
        _apply_pending_density_if_any()
        st.radio(
            "Density",
            ["Compact", "Comfy"],
            index=0 if st.session_state.get("density", "Compact") == "Compact" else 1,
            horizontal=True,
            key="density",
        )
        with st.popover("Export PDF tips"):
            st.markdown(
                """
                - Set Layout to **Landscape**
                - Set Scale to **75–85%**
                - Set Margins to **Narrow**
                - Ensure expanders are **collapsed** (Compact density) to reduce height
                - Use the **Download history CSV** button for data export
                """
            )
        # Help popover with a short FAQ
        with st.popover("Help"):
            st.markdown(
                """
                - **How are emissions calculated?** Using standard factors per activity (kg CO₂ per unit).
                - **Why is bicycle 0?** Cycling has negligible direct CO₂ emissions in this model.
                - **How do I save/export?** Click "Calculate & Save" then download the CSV in Dashboard.
                - **Tips to reduce CO₂?** See the Eco tip card and focus on your biggest source first.
                
                <br/>
                <a href="#secrets" style="text-decoration:none;">
                  <span style="display:inline-block;padding:2px 8px;border-radius:12px;background:#eef;border:1px solid #ccd;color:#223;">🔐 Secrets (README)</span>
                </a>
                <div style="font-size:0.9em;color:#555;">Configure your OPENAI_API_KEY via <code>.env</code>. See README → Secrets.</div>
                """,
                unsafe_allow_html=True,
            )
        # Demo mode: force Compact, load demo values, auto-generate tip
        demo_mode = st.checkbox(
            "Demo mode",
            value=st.session_state.get("demo_mode", False),
            help="Force Compact density, load demo values, and auto-generate a tip.",
            key="demo_mode",
        )
        # Subtle status line about snapshot (for demo debugging)
        if demo_mode:
            _snap = st.session_state.get("demo_snapshot")
            if isinstance(_snap, dict) and _snap.get("ts"):
                st.caption(f"Demo snapshot captured at {_snap['ts']}")
                with st.popover("View snapshot detail"):
                    st.caption(f"Density before demo: {_snap.get('density', 'Comfy')}")
                    inputs = _snap.get("inputs", {})
                    if inputs:
                        st.json(inputs)
                    else:
                        st.write("No inputs captured in snapshot.")
            else:
                st.caption("Demo snapshot: none yet")
        if demo_mode and not st.session_state.get("demo_mode_applied", False):
            # Snapshot current density and inputs to allow restore on exit
            input_keys = [
                # Energy
                "electricity_kwh",
                "natural_gas_m3",
                "hot_water_liter",
                "cold_water_liter",
                "district_heating_kwh",
                "propane_liter",
                "fuel_oil_liter",
                # Transport
                "bus_km",
                "train_km",
                "bicycle_km",
                "petrol_liter",
                "diesel_liter",
                "flight_short_km",
                "flight_long_km",
                # Meals
                "meat_kg",
                "chicken_kg",
                "eggs_kg",
                "dairy_kg",
                "vegetarian_kg",
                "vegan_kg",
            ]
            st.session_state["demo_snapshot"] = {
                "density": st.session_state.get("density", "Comfy"),
                "inputs": {f"in_{k}": st.session_state.get(f"in_{k}", 0.0) for k in input_keys},
                "ts": dt.datetime.now().isoformat(),
            }
            # Queue density to Compact
            st.session_state["_pending_density"] = "Compact"
            # Load representative demo values
            demo_vals = {
                # Energy
                "electricity_kwh": 6.0,
                "natural_gas_m3": 1.2,
                "hot_water_liter": 60,
                # Transport
                "bus_km": 10,
                "train_km": 0,
                "petrol_liter": 2.5,
                # Meals
                "meat_kg": 0.15,
                "dairy_kg": 0.3,
                "vegetarian_kg": 0.2,
            }
            st.session_state["_pending_values"] = demo_vals
            # Auto-generate in Eco Tips on next run
            st.session_state["tips_autogen"] = True
            st.session_state["demo_mode_applied"] = True
            try:
                st.rerun()
            except Exception:
                pass
        # Exit Demo Mode helper: resets inputs and layout back to defaults
        if demo_mode:
            demo_keys = [
                # Energy
                "electricity_kwh",
                "natural_gas_m3",
                "hot_water_liter",
                "cold_water_liter",
                "district_heating_kwh",
                "propane_liter",
                "fuel_oil_liter",
                # Transport
                "bus_km",
                "train_km",
                "bicycle_km",
                "petrol_liter",
                "diesel_liter",
                "flight_short_km",
                "flight_long_km",
                # Meals
                "meat_kg",
                "eggs_kg",
                "dairy_kg",
                "vegetarian_kg",
                "chicken_kg",
                "vegan_kg",
            ]
            if st.button("Exit Demo Mode"):
                # Restore from snapshot if available; otherwise clear to zeros and comfy
                snap = st.session_state.get("demo_snapshot")
                if snap and isinstance(snap, dict):
                    # Convert stored 'in_*' keys back to canonical field keys
                    restored = {}
                    for key, val in snap.get("inputs", {}).items():
                        if key.startswith("in_"):
                            restored[key[3:]] = val
                    st.session_state["_pending_values"] = restored
                    st.session_state["_pending_density"] = snap.get("density", "Comfy")
                else:
                    st.session_state["_pending_values"] = {k: 0.0 for k in demo_keys}
                    st.session_state["_pending_density"] = "Comfy"
                st.session_state["tips_autogen"] = False
                st.session_state["demo_mode_applied"] = False
                # Do NOT set the widget key directly here; queue an off toggle instead
                st.session_state["_pending_demo_off"] = True
                st.session_state.pop("demo_snapshot", None)
                try:
                    st.rerun()
                except Exception:
                    pass

        # Hidden debug controls
        with st.expander("Debug (performance)", expanded=False):
            default_th = st.session_state.get("spinner_threshold", 0.3)
            th = st.slider("Spinner threshold (seconds)", 0.0, 2.0, float(default_th), 0.05)
            st.session_state["spinner_threshold"] = float(th)
            st.checkbox(
                "Enable performance logging (perf_log.csv)",
                value=st.session_state.get("perf_logging", False),
                key="perf_logging",
                help="Append eco-tip generation timings to perf_log.csv",
            )
            st.markdown(
                """
                <a href="#secrets" style="text-decoration:none;">
                  <span style="display:inline-block;padding:2px 8px;border-radius:12px;background:#eef;border:1px solid #ccd;color:#223;">🔐 Secrets (README)</span>
                </a>
                <div style="font-size:0.9em;color:#555;">Configure your OPENAI_API_KEY via <code>.env</code>. See README → Secrets.</div>
                """,
                unsafe_allow_html=True,
            )
        # Copy shareable link button (copies current URL with density param)
        st.markdown(
            """
            <button id=\"copy-link-btn\" style=\"margin-top:0.25rem;\">Copy shareable link</button>
            <script>
            const btn = document.getElementById('copy-link-btn');
            if (btn) {
              btn.addEventListener('click', async () => {
                try {
                  await navigator.clipboard.writeText(window.location.href);
                  const old = btn.textContent;
                  btn.textContent = 'Copied!';
                  setTimeout(() => { btn.textContent = old; }, 1500);
                } catch (e) {
                  btn.textContent = 'Copy failed';
                  setTimeout(() => { btn.textContent = 'Copy shareable link'; }, 1500);
                }
              });
            }
            </script>
            """,
            unsafe_allow_html=True,
        )
        # Reset layout button: revert to Compact density and update URL
        if st.button("Reset layout", type="secondary"):
            st.session_state["_pending_density"] = "Compact"
            try:
                st.query_params["density"] = "Compact"
            except Exception:
                pass
            st.success("Layout reset to Compact. Collapse expanders for best PDF.")
            try:
                st.rerun()
            except Exception:
                pass
        # Clear inputs button: zero all input fields
        if st.button("Clear inputs", help="Reset all fields to zero for today’s entry."):
            try:
                for _k in ALL_KEYS:
                    _sk = f"in_{_k}"
                    if _sk in st.session_state:
                        st.session_state[_sk] = 0.0
            except Exception:
                pass
            st.success("Inputs cleared.")
        # Demo and preset fillers
        with st.popover("Prefill demos/presets"):
            st.markdown("Pick a scenario to quickly populate inputs for demos.")
            c_demo, c_p1, c_p2 = st.columns(3)
            def _apply_values(vals: dict):
                # Queue values to apply before widgets are instantiated, then rerun
                st.session_state["_pending_values"] = {k: float(v) for k, v in vals.items()}
                try:
                    st.rerun()
                except Exception:
                    pass
            with c_demo:
                if st.button("Demo values"):
                    _apply_values({
                        # Energy
                        "electricity_kwh": 8,
                        "natural_gas_m3": 1.2,
                        "hot_water_liter": 60,
                        # Transport
                        "bus_km": 10,
                        "train_km": 0,
                        "petrol_liter": 2.5,
                        # Meals
                        "meat_kg": 0.15,
                        "dairy_kg": 0.3,
                        "vegetarian_kg": 0.2,
                    })
            with c_p1:
                if st.button("No car day"):
                    _apply_values({
                        "petrol_liter": 0,
                        "diesel_liter": 0,
                        "bus_km": 12,
                        "train_km": 6,
                        "bicycle_km": 5,
                    })
            with c_p2:
                if st.button("Vegetarian day"):
                    _apply_values({
                        "meat_kg": 0,
                        "chicken_kg": 0,
                        "vegetarian_kg": 0.6,
                        "vegan_kg": 0.2,
                        "dairy_kg": 0.25,
                    })
            c_p3, _, _ = st.columns(3)
            with c_p3:
                if st.button("Business trip"):
                    _apply_values({
                        "flight_short_km": 600,
                        "train_km": 20,
                        "electricity_kwh": 6,
                        "meat_kg": 0.25,
                    })

    # IMPORTANT: assign density BEFORE using it below
    density = st.session_state["density"]

    # Update URL query param to reflect current density (new API)
    try:
        st.query_params["density"] = density
    except Exception:
        pass

    # Heights and paddings based on density
    if density == "Compact":
        pad_top, pad_bottom = "1rem", "1rem"
        table_height = 150
        trend_height = 180
        bar_height = 180
        per_activity_height = 260
        expander_default = False
    else:
        pad_top, pad_bottom = "2rem", "2rem"
        table_height = 220
        trend_height = 260
        bar_height = 260
        per_activity_height = 360
        expander_default = True

    # Hide Streamlit default menu, footer, and header for cleaner PDF export
    st.markdown(
        f"""
        <style>
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        header {{visibility: hidden;}}
        .block-container {{padding-top: {pad_top}; padding-bottom: {pad_bottom};}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Top row: date and action area
    top_c1, top_c2 = st.columns([1, 2])
    with top_c1:
        selected_date = st.date_input("Date", value=dt.date.today())
    with top_c2:
        st.write("")

    def _apply_pending_values_if_any():
        """Apply any queued preset/demo values before widgets are created."""
        pending = st.session_state.get("_pending_values")
        if isinstance(pending, dict) and pending:
            for k, v in pending.items():
                st.session_state[f"in_{k}"] = float(v)
            st.session_state.pop("_pending_values", None)

    _apply_pending_values_if_any()

    with st.form("daily_input"):
        # Inputs grouped in compact expanders (density controlled)
        with st.expander("Energy inputs", expanded=expander_default):
            e1, e2, e3 = st.columns(3)
            with e1:
                electricity = st.number_input("Electricity (kWh)", value=0.0, min_value=0.0, step=0.1, key="in_electricity_kwh", help="Enter a number ≥ 0")
                _e = _coerce_float(electricity)
                if _e is None or (_e is not None and _e < 0):
                    st.markdown("<div style='color:#b00020;font-size:0.9em;'>Enter a number ≥ 0</div>", unsafe_allow_html=True)
                natural_gas = st.number_input("Natural Gas (m³)", value=0.0, min_value=0.0, step=0.1, key="in_natural_gas_m3", help="Enter a number ≥ 0")
            with e2:
                hot_water = st.number_input("Hot Water (L)", value=0.0, min_value=0.0, step=1.0, key="in_hot_water_liter", help="Enter a number ≥ 0")
                cold_water = st.number_input("Cold/Chilled Water (L)", value=0.0, min_value=0.0, step=1.0, key="in_cold_water_liter", help="Enter a number ≥ 0")
            with e3:
                district_heating = st.number_input("District Heating (kWh)", value=0.0, min_value=0.0, step=0.1, key="in_district_heating_kwh", help="Enter a number ≥ 0")
                propane = st.number_input("Propane (L)", value=0.0, min_value=0.0, step=0.1, key="in_propane_liter", help="Enter a number ≥ 0")
                fuel_oil = st.number_input("Fuel Oil (L)", value=0.0, min_value=0.0, step=0.1, key="in_fuel_oil_liter", help="Enter a number ≥ 0")

        with st.expander("Transport inputs", expanded=expander_default):
            t1, t2, t3 = st.columns(3)
            with t1:
                petrol = st.number_input("Car Petrol (L)", value=0.0, min_value=0.0, step=0.1, key="in_petrol_liter", help="Enter a number ≥ 0")
                _p = _coerce_float(petrol)
                if _p is None or (_p is not None and _p < 0):
                    st.markdown("<div style='color:#b00020;font-size:0.9em;'>Enter a number ≥ 0</div>", unsafe_allow_html=True)
                diesel = st.number_input("Car Diesel (L)", value=0.0, min_value=0.0, step=0.1, key="in_diesel_liter", help="Enter a number ≥ 0")
            with t2:
                bus = st.number_input("Bus (km)", value=0.0, min_value=0.0, step=1.0, key="in_bus_km", help="Enter a number ≥ 0")
                train = st.number_input("Train (km)", value=0.0, min_value=0.0, step=1.0, key="in_train_km", help="Enter a number ≥ 0")
                bicycle = st.number_input("Bicycle (km)", value=0.0, min_value=0.0, step=1.0, key="in_bicycle_km", help="Enter a number ≥ 0")
            with t3:
                flight_short = st.number_input("Flight Short (km)", value=0.0, min_value=0.0, step=1.0, key="in_flight_short_km", help="Enter a number ≥ 0")
                flight_long = st.number_input("Flight Long (km)", value=0.0, min_value=0.0, step=1.0, key="in_flight_long_km", help="Enter a number ≥ 0")

        with st.expander("Meals inputs", expanded=expander_default):
            m1, m2, m3 = st.columns(3)
            with m1:
                meat = st.number_input("Meat (kg)", value=0.0, min_value=0.0, step=0.1, key="in_meat_kg", help="Enter a number ≥ 0")
                _m = _coerce_float(meat)
                if _m is None or (_m is not None and _m < 0):
                    st.markdown("<div style='color:#b00020;font-size:0.9em;'>Enter a number ≥ 0</div>", unsafe_allow_html=True)
                chicken = st.number_input("Chicken (kg)", value=0.0, min_value=0.0, step=0.1, key="in_chicken_kg", help="Enter a number ≥ 0")
            with m2:
                eggs = st.number_input("Eggs (kg)", value=0.0, min_value=0.0, step=0.1, key="in_eggs_kg", help="Enter a number ≥ 0")
                dairy = st.number_input("Dairy (kg)", value=0.0, min_value=0.0, step=0.1, key="in_dairy_kg", help="Enter a number ≥ 0")
            with m3:
                vegetarian = st.number_input("Vegetarian (kg)", value=0.0, min_value=0.0, step=0.1, key="in_vegetarian_kg", help="Enter a number ≥ 0")
                vegan = st.number_input("Vegan (kg)", value=0.0, min_value=0.0, step=0.1, key="in_vegan_kg", help="Enter a number ≥ 0")

        submitted = st.form_submit_button("Calculate & Save")

    # Gather input into a dict compatible with CO2_FACTORS
    user_data = {
        "electricity_kwh": electricity,
        "natural_gas_m3": natural_gas,
        "hot_water_liter": hot_water,
        "cold_water_liter": cold_water,
        "district_heating_kwh": district_heating,
        "propane_liter": propane,
        "fuel_oil_liter": fuel_oil,
        "petrol_liter": petrol,
        "diesel_liter": diesel,
        "bus_km": bus,
        "train_km": train,
        "bicycle_km": bicycle,
        "flight_short_km": flight_short,
        "flight_long_km": flight_long,
        "meat_kg": meat,
        "chicken_kg": chicken,
        "eggs_kg": eggs,
        "dairy_kg": dairy,
        "vegetarian_kg": vegetarian,
        "vegan_kg": vegan,
    }

    # Global input hint (tooltip-style note)
    st.markdown("<div style='color:#5f6368;font-size:0.9em;'>Hint: All numeric inputs should be <b>≥ 0</b>. Enter whole numbers or decimals as needed.</div>", unsafe_allow_html=True)

    # Inline warnings near inputs (if any invalid fields)
    show_input_warnings(user_data)

    # Calculate total emissions
    emissions = calculate_co2(user_data)
    # Store for cross-tab visibility (Eco Tips tab)
    st.session_state["emissions_today"] = float(emissions)

    # Compute per-activity once for optional breakdown tab
    per_activity = calculate_co2_breakdown(user_data)

    # Load history for KPIs and visuals
    history_df = load_history()
    yesterday_total = get_yesterday_total(history_df, selected_date)
    delta_pct = percentage_change(yesterday_total, emissions)
    streak = compute_streak(history_df, selected_date)

    # KPIs (compact)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total", fmt_emissions(emissions))
    c2.metric("Δ vs. Yesterday", f"{delta_pct:.2f}%")
    c3.metric("Streak", f"{streak} day(s)")

    # Tabs for Dashboard and Breakdown
    tab_dashboard, tab_history, tab_breakdown, tab_tips = st.tabs(["📊 Dashboard", "📜 History", "📉 Breakdown", "💡 Eco Tips"])

    with tab_dashboard:
        # Two-column layout for compact one-page UI
        left_col, right_col = st.columns([2, 1])

        with left_col:
            # Category-wise table
            cat_emissions = compute_category_emissions(user_data)
            st.caption("Category totals (kg CO₂)")
            st.dataframe(
                pd.DataFrame.from_dict(cat_emissions, orient="index", columns=["kg CO₂"]),
                use_container_width=True,
                height=table_height,
            )

            st.caption("Today's category breakdown")
            st.bar_chart(pd.Series(cat_emissions, name="kg CO₂"), height=bar_height)

        with right_col:
            # Save after calculation
            if submitted:
                invalid = find_invalid_fields(user_data)
                if invalid:
                    bad_list = ", ".join(invalid)
                    st.warning(f"Some inputs look invalid (negative or non-numeric): {bad_list}. Please correct them before saving.")
                    # Optional logging
                    if st.session_state.get("perf_logging", False):
                        log_path = os.path.join(os.getcwd(), "perf_log.csv")
                        file_exists = os.path.exists(log_path)
                        try:
                            with open(log_path, mode="a", newline="", encoding="utf-8") as f:
                                writer = csv.writer(f)
                                if not file_exists:
                                    writer.writerow(["timestamp", "elapsed_s", "emissions_kg"])  # header
                                writer.writerow([dt.datetime.now().isoformat(), "warning:invalid_inputs", f"{emissions:.4f}"])
                        except Exception:
                            pass
                elif not has_meaningful_input(user_data):
                    st.warning("No valid input detected – please log at least one activity before saving.")
                    if st.session_state.get("perf_logging", False):
                        log_path = os.path.join(os.getcwd(), "perf_log.csv")
                        file_exists = os.path.exists(log_path)
                        try:
                            with open(log_path, mode="a", newline="", encoding="utf-8") as f:
                                writer = csv.writer(f)
                                if not file_exists:
                                    writer.writerow(["timestamp", "elapsed_s", "emissions_kg"])  # header
                                writer.writerow([dt.datetime.now().isoformat(), "warning:no_inputs", f"{emissions:.4f}"])
                        except Exception:
                            pass
                else:
                    save_entry(selected_date, user_data, emissions)
                    st.success("Saved.")

            # Visualizations (reduced height)
            history_df = load_history()  # reload after potential save
            if not history_df.empty:
                st.caption("Trend (Total kg CO₂)")
                history_df_display = history_df.copy()
                history_df_display["date"] = history_df_display["date"].dt.date
                st.line_chart(history_df_display.set_index("date")["total_kg"], height=trend_height)

                # CSV export button
                csv_buf = io.StringIO()
                history_df.to_csv(csv_buf, index=False)
                st.download_button(
                    label="⬇️ Download history CSV",
                    data=csv_buf.getvalue(),
                    file_name="history.csv",
                    mime="text/csv",
                    key="download_history_csv_dashboard",
                )

            # Eco tip and status (compact)
            st.caption("Eco tip & status")
            start_time = time.time()
            placeholder = st.empty()
            tip = None
            threshold = float(st.session_state.get("spinner_threshold", 0.3))
            # Run tip generation in a background thread
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(generate_tip, user_data, emissions)
                spinner_shown = False
                # Poll until done; when threshold reached, block within spinner context
                while True:
                    if fut.done():
                        tip = fut.result()
                        break
                    elapsed_loop = time.time() - start_time
                    if not spinner_shown and elapsed_loop > threshold:
                        with placeholder.container():
                            with st.spinner("Generating eco-tip..."):
                                tip = fut.result()  # wait until complete while spinner shows
                        spinner_shown = True
                        break
                    time.sleep(0.05)
            elapsed = time.time() - start_time
            icon, dom_cat = dominant_category_icon(user_data)
            st.session_state["last_tip"] = tip
            st.session_state["last_tip_icon"] = icon
            st.success(f"{icon} {tip}")
            st.caption(f"Tip generated in {elapsed:.2f}s")
            # Optional perf logging
            if st.session_state.get("perf_logging", False):
                log_path = os.path.join(os.getcwd(), "perf_log.csv")
                file_exists = os.path.exists(log_path)
                try:
                    with open(log_path, mode="a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        if not file_exists:
                            writer.writerow(["timestamp", "elapsed_s", "emissions_kg"])  # header
                        writer.writerow([dt.datetime.now().isoformat(), f"{elapsed:.4f}", f"{emissions:.4f}"])
                except Exception:
                    pass
            st.success(status_message(emissions))

            # Badges (compact list)
            st.caption("Badges")
            badges = award_badges(emissions, streak, history_df)
            if badges:
                for b in badges:
                    st.markdown(f"- {b}")
            else:
                st.write("Log entries to start earning badges!")

        # Second row: mini sparklines by category
        if not history_df.empty:
            st.divider()
            st.caption("Mini trends by category")

            def _category_series(df: pd.DataFrame, keys: list[str]) -> pd.Series | None:
                present = [k for k in keys if k in df.columns]
                if not present:
                    return None
                s = pd.Series(0.0, index=df.index)
                for k in present:
                    factor = CO2_FACTORS.get(k)
                    s = s + df[k].fillna(0).astype(float) * factor
                return s

            def _seven_day_delta(s: pd.Series):
                if s is None or s.empty:
                    return None, None
                s = s.dropna()
                if len(s) < 2:
                    return None, None
                last7 = float(s.iloc[-7:].sum())
                prev7 = float(s.iloc[-14:-7].sum()) if len(s) >= 14 else 0.0
                return last7, percentage_change(prev7, last7)

            df_sorted = history_df.sort_values("date").copy()
            df_sorted_indexed = df_sorted.set_index("date")

            energy_s = _category_series(df_sorted, CATEGORY_MAP["Energy"]) 
            energy_s = energy_s if (energy_s is not None and not energy_s.empty) else pd.Series(dtype=float)
            transport_s = _category_series(df_sorted, CATEGORY_MAP["Transport"]) 
            transport_s = transport_s if (transport_s is not None and not transport_s.empty) else pd.Series(dtype=float)
            meals_s = _category_series(df_sorted, CATEGORY_MAP["Meals"]) 
            meals_s = meals_s if (meals_s is not None and not meals_s.empty) else pd.Series(dtype=float)

            mini_height = 120 if density == "Compact" else 160
            c_en, c_tr, c_me = st.columns(3)
            with c_en:
                st.markdown("**Energy**")
                if not energy_s.empty:
                    st.line_chart(energy_s.set_axis(df_sorted_indexed.index), height=mini_height)
                    en_last7, en_pct = _seven_day_delta(energy_s)
                    if en_last7 is not None:
                        st.metric("7d total", f"{en_last7:.2f} kg", f"{en_pct:.1f}%", delta_color="inverse")
                    else:
                        st.caption("Not enough data yet")
                else:
                    st.write("No data yet")
            with c_tr:
                st.markdown("**Transport**")
                if not transport_s.empty:
                    st.line_chart(transport_s.set_axis(df_sorted_indexed.index), height=mini_height)
                    tr_last7, tr_pct = _seven_day_delta(transport_s)
                    if tr_last7 is not None:
                        st.metric("7d total", f"{tr_last7:.2f} kg", f"{tr_pct:.1f}%", delta_color="inverse")
                    else:
                        st.caption("Not enough data yet")
                else:
                    st.write("No data yet")
            with c_me:
                st.markdown("**Meals**")
                if not meals_s.empty:
                    st.line_chart(meals_s.set_axis(df_sorted_indexed.index), height=mini_height)
                    me_last7, me_pct = _seven_day_delta(meals_s)
                    if me_last7 is not None:
                        st.metric("7d total", f"{me_last7:.2f} kg", f"{me_pct:.1f}%", delta_color="inverse")
                    else:
                        st.caption("Not enough data yet")
                else:
                    st.write("No data yet")

    with tab_history:
        st.header("Saved History")
        history_all = load_history()
        if history_all.empty:
            st.info("No entries yet. Click Calculate & Save on the Dashboard to start your history.")
        else:
            st.caption("All logged entries (most recent shown first)")
            display_df = history_all.copy()
            display_df["date"] = display_df["date"].dt.date
            st.dataframe(display_df.sort_values("date", ascending=False), use_container_width=True, height=per_activity_height)

            # CSV export
            csv_buf = io.StringIO()
            history_all.to_csv(csv_buf, index=False)
            st.download_button(
                label="⬇️ Download history CSV",
                data=csv_buf.getvalue(),
                file_name="history.csv",
                mime="text/csv",
                key="download_history_csv_history_tab",
            )

    with tab_breakdown:
        st.caption("Per-activity emissions (kg CO₂)")
        if per_activity:
            st.dataframe(
                pd.Series(per_activity, name="kg CO₂").sort_values(ascending=False).to_frame(),
                use_container_width=True,
                height=per_activity_height,
            )
        else:
            st.info("No per-activity data to show yet.")

    with tab_tips:
        icon_hdr, dom_hdr = dominant_category_icon(user_data)
        st.subheader(f"{icon_hdr} Personalized Eco Tips")
        st.caption(f"Get a personalized tip based on today’s inputs and total emissions. Dominant today: {dom_hdr}.")

        # API source badge (GPT vs Fallback)
        source = st.session_state.get("last_tip_source") or ("GPT" if LAST_TIP_SOURCE == "gpt" else ("Fallback" if LAST_TIP_SOURCE == "fallback" else "Unknown"))
        badge_color = "#16a34a" if source == "GPT" else ("#6b7280" if source == "Fallback" else "#9ca3af")
        st.markdown(f"<div style='display:inline-block;padding:2px 8px;border-radius:12px;background:{badge_color};color:white;font-size:0.85em;'>AI source: {source}</div>", unsafe_allow_html=True)

        # Compact summary of today's inputs for context
        st.markdown("**Summary of today’s activities**")
        summary_str = format_summary(user_data)
        # Colored tag summary (HTML)
        st.markdown(format_summary_html(user_data), unsafe_allow_html=True)
        # Explicitly show today's total emissions coming from backend/session
        em_today = float(st.session_state.get("emissions_today", emissions))
        st.metric("Today's total (backend)", fmt_emissions(em_today))
        # Copy-ready block using Streamlit's built-in copy icon on code blocks
        st.caption("Copy-ready summary (use the copy icon on the right):")
        st.code(summary_str)

        # Download button for the summary
        st.download_button(
            label="⬇️ Download summary (.txt)",
            data=summary_str,
            file_name="summary.txt",
            mime="text/plain",
            key="download_summary_txt_tips_tab",
        )

        # Server-side PDF export (beta)
        st.divider()
        st.caption("Export as PDF (server-side)")
        with st.expander("PDF Branding & Options", expanded=False):
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                pdf_title = st.text_input(
                    "PDF title",
                    value=st.session_state.get("pdf_title", "Sustainability Tracker — Eco Tips Summary"),
                    key="pdf_title",
                    help="Shown at the top of the PDF",
                )
            with c2:
                # Auto-detect theme base and set sensible defaults
                detected_theme = st.get_option("theme.base") or "light"
                default_primary = "#60A5FA" if detected_theme == "light" else "#93C5FD"
                default_text = "#111827" if detected_theme == "light" else "#F3F4F6"
                default_chart_bg = "#FFFFFF" if detected_theme == "light" else "#111827"
                pdf_primary_color = st.color_picker(
                    "Accent color",
                    value=st.session_state.get("pdf_primary_color", default_primary),
                    key="pdf_primary_color",
                )
            with c3:
                pdf_include_pie = st.checkbox(
                    "Include pie",
                    value=st.session_state.get("pdf_include_pie", True),
                    key="pdf_include_pie",
                    help="Include per-category pie chart",
                )
                pdf_include_spark = st.checkbox(
                    "Include sparklines",
                    value=st.session_state.get("pdf_include_spark", True),
                    key="pdf_include_spark",
                    help="Include 7-day per-category mini charts",
                )
            cT1, cT2 = st.columns(2)
            with cT1:
                pdf_text_color = st.color_picker("Text color", value=st.session_state.get("pdf_text_color", default_text), key="pdf_text_color")
            with cT2:
                pdf_chart_bg = st.color_picker("Chart background", value=st.session_state.get("pdf_chart_bg", default_chart_bg), key="pdf_chart_bg")
            c4, c5, c6 = st.columns(3)
            with c4:
                pdf_side_margin = st.number_input("Side margin (cm)", min_value=1.0, max_value=3.0, value=float(st.session_state.get("pdf_side_margin", 2.0)), step=0.1, key="pdf_side_margin")
            with c5:
                pdf_top_margin = st.number_input("Top margin (cm)", min_value=1.0, max_value=3.0, value=float(st.session_state.get("pdf_top_margin", 2.0)), step=0.1, key="pdf_top_margin")
            with c6:
                pdf_bottom_margin = st.number_input("Bottom margin (cm)", min_value=1.0, max_value=3.0, value=float(st.session_state.get("pdf_bottom_margin", 1.8)), step=0.1, key="pdf_bottom_margin")
            c7, c8 = st.columns([2, 1])
            with c7:
                pdf_footer_text = st.text_input("Footer text", value=st.session_state.get("pdf_footer_text", " 2025 Sustainability Tracker • https://example.com"), key="pdf_footer_text")
            with c8:
                pdf_include_footer = st.checkbox("Include footer", value=st.session_state.get("pdf_include_footer", True), key="pdf_include_footer")
            logo_file = st.file_uploader("Logo (PNG/JPG)", type=["png", "jpg", "jpeg"], key="pdf_logo_upload")
            if logo_file is None:
                logo_path_hint = os.path.join(os.path.dirname(__file__), "logo.png")
                if not os.path.exists(logo_path_hint):
                    st.caption("No logo uploaded and no logo.png found. A styled fallback badge will be drawn. Place a logo.png at the project root to override.")

        if st.button("Generate Eco Tips PDF (beta)"):
            tip_for_pdf = st.session_state.get("last_tip", "")
            src_label = st.session_state.get("last_tip_source") or ("GPT" if LAST_TIP_SOURCE == "gpt" else ("Fallback" if LAST_TIP_SOURCE == "fallback" else "Unknown"))
            date_str = selected_date.isoformat() if isinstance(selected_date, (dt.date, dt.datetime)) else str(selected_date)
            # Prepare 7-day per-category sparkline data from history
            spark = {}
            try:
                _hist = load_history()
                if not _hist.empty:
                    dfh = _hist.copy()
                    dfh["date"] = pd.to_datetime(dfh["date"]).dt.date
                    last_dates = sorted(dfh["date"].unique())[-7:]
                    for d in last_dates:
                        row = dfh[dfh["date"] == d]
                        if row.empty:
                            continue
                        rdict = {k: float(row.iloc[-1].get(k, 0) or 0) for k in ALL_KEYS if k in row.columns}
                        cat_vals = compute_category_emissions(rdict)
                        for cat, val in cat_vals.items():
                            spark.setdefault(cat, []).append(float(val))
            except Exception:
                spark = {}
            # Prefer uploaded logo; fallback to project's logo.png path if present
            logo_bytes = None
            if logo_file is not None:
                logo_bytes = logo_file.read()
            else:
                logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
                if os.path.exists(logo_path):
                    try:
                        with open(logo_path, "rb") as lf:
                            logo_bytes = lf.read()
                    except Exception:
                        logo_bytes = None
            pdf_bytes, err = build_eco_tips_pdf(
                summary_str, tip_for_pdf, em_today, date_str, src_label, per_activity, compute_category_emissions(user_data), {
                "today_total": fmt_emissions(em_today),
                "yesterday_total": fmt_emissions(yesterday_total) if 'yesterday_total' in locals() else "",
                "delta_pct": f"{percentage_change(yesterday_total, em_today):.2f}%" if 'yesterday_total' in locals() else "",
                "streak_days": f"{streak} days" if 'streak' in locals() else "",
            }, logo_bytes=logo_bytes, title_text=pdf_title, primary_color=pdf_primary_color, include_pie=bool(pdf_include_pie), include_sparklines=bool(pdf_include_spark), spark_data=spark, footer_text=pdf_footer_text if pdf_include_footer else None, margins_cm={"side": float(pdf_side_margin), "top": float(pdf_top_margin), "bottom": float(pdf_bottom_margin)}, text_hex=pdf_text_color, chart_bg_hex=pdf_chart_bg)
            if pdf_bytes:
                st.download_button(
                    label=" Download Eco Tips PDF",
                    data=pdf_bytes,
                    file_name=f"eco_tips_{date_str}.pdf",
                    mime="application/pdf",
                    key="download_eco_tips_pdf",
                )
            else:
                st.error(err or "PDF generation failed.")

def build_eco_tips_pdf(summary_text: str, tip_text: str, emissions: float, date_str: str, source_label: str, per_activity: dict | None, per_category: dict | None, kpis: dict | None, logo_bytes: bytes | None = None, title_text: str | None = None, primary_color: str | None = None, include_pie: bool = True, include_sparklines: bool = True, spark_data: dict | None = None, footer_text: str | None = None, margins_cm: dict | None = None, text_hex: str | None = None, chart_bg_hex: str | None = None) -> tuple[bytes | None, str | None]:
    """Build a simple landscape PDF with today's summary, tip, and optional per-activity table.
    Returns (pdf_bytes, error_message). If error_message is not None, generation failed.
    """
    try:
        # Lazy import so the app runs even if reportlab isn't installed
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import cm
        from reportlab.lib.utils import simpleSplit, ImageReader
        from reportlab.lib.colors import HexColor
    except Exception as e:
        return None, f"ReportLab not available: {e}. Install with: pip install reportlab"

    # Try to import matplotlib for basic charts (optional)
    mpl_ok = True
    try:
        import matplotlib.pyplot as plt
    except Exception:
        mpl_ok = False

    try:
        buf = io.BytesIO()
        page_size = landscape(A4)
        c = canvas.Canvas(buf, pagesize=page_size)
        width, height = page_size
        # Margins
        side_m = (margins_cm or {}).get("side", 2.0) * cm
        top_m = (margins_cm or {}).get("top", 2.0) * cm
        bottom_m = (margins_cm or {}).get("bottom", 1.8) * cm
        left = side_m
        right = width - side_m

        # Colors
        try:
            if text_hex:
                c.setFillColor(HexColor(text_hex))
        except Exception:
            pass

        # Footer helper
        def _draw_footer():
            if footer_text:
                c.setFont("Helvetica", 9)
                # Text color
                try:
                    if text_hex:
                        c.setFillColor(HexColor(text_hex))
                except Exception:
                    c.setFillColorRGB(0, 0, 0)
                c.drawString(left, bottom_m - 0.4*cm, footer_text)
                try:
                    c.drawRightString(right, bottom_m - 0.4*cm, f"Page {c.getPageNumber()}")
                except Exception:
                    pass

        # Page break helper
        def _show_page():
            _draw_footer()
            c.showPage()
            # Reset text color after page break
            try:
                if text_hex:
                    c.setFillColor(HexColor(text_hex))
            except Exception:
                c.setFillColorRGB(0, 0, 0)

        # Title
        y = height - top_m
        c.setTitle("Eco Tips Summary")
        # Slightly larger heading for better hierarchy
        c.setFont("Helvetica-Bold", 19)
        # Optional logo (bytes) on the left and custom title/color
        draw_title = title_text or "Sustainability Tracker — Eco Tips Summary"
        try:
            if primary_color:
                c.setFillColor(HexColor(primary_color))
        except Exception:
            pass
        try:
            if logo_bytes:
                img = ImageReader(io.BytesIO(logo_bytes))
                c.drawImage(img, left, y-0.5*cm, width=2.2*cm, height=2.2*cm, preserveAspectRatio=True, mask='auto')
                c.drawString(left + 2.5*cm, y, draw_title)
            else:
                # Vector fallback badge (no file needed)
                try:
                    # Colored rounded rect badge
                    if primary_color:
                        c.setFillColor(HexColor(primary_color))
                    c.roundRect(left, y-0.5*cm, 2.2*cm, 2.2*cm, 0.3*cm, fill=1, stroke=0)
                    # Badge initials
                    c.setFillColorRGB(1, 1, 1)
                    c.setFont("Helvetica-Bold", 14)
                    c.drawCentredString(left + 1.1*cm, y + 0.5*cm, "ST")
                except Exception:
                    pass
                # Title next to badge
                c.setFillColorRGB(0, 0, 0)
                c.drawString(left + 2.5*cm, y, draw_title)
        except Exception:
            c.drawString(left, y, draw_title)
        
        # Reset text color for body
        try:
            if text_hex:
                c.setFillColor(HexColor(text_hex))
            else:
                c.setFillColorRGB(0, 0, 0)
        except Exception:
            c.setFillColorRGB(0, 0, 0)
        y -= 0.4*cm

        # Meta line
        c.setFont("Helvetica", 11)
        c.drawString(left, y, f"Date: {date_str}    Total: {fmt_emissions(float(emissions))}    AI source: {source_label}")
        y -= 0.8*cm

        # KPI line (if provided)
        if isinstance(kpis, dict):
            c.setFont("Helvetica-Bold", 12)
            c.drawString(left, y, "Key metrics:")
            y -= 0.6*cm
            c.setFont("Helvetica", 10.5)
            for label in ["today_total", "yesterday_total", "delta_pct", "streak_days"]:
                if label in kpis:
                    c.drawString(left, y, f"- {label.replace('_',' ').title()}: {kpis[label]}")
                    y -= 0.48*cm
                    if y < bottom_m + 2*cm:
                        _show_page(); y = height - top_m

        # 7-day sparklines per category (if provided)
        if include_sparklines and mpl_ok and isinstance(spark_data, dict) and spark_data:
            try:
                # Arrange small charts in a grid
                cols = 3
                cell_w, cell_h = 8*cm, 3*cm
                c.setFont("Helvetica-Bold", 12)
                c.drawString(left, y, "7-day category trends:")
                y -= 0.6*cm
                x0, y0 = left, y
                i = 0
                for cat, series in spark_data.items():
                    fig, ax = plt.subplots(figsize=(cell_w/96, cell_h/96), dpi=96)
                    # Theme-aware chart styling
                    if chart_bg_hex:
                        try:
                            fig.patch.set_facecolor(chart_bg_hex)
                            ax.set_facecolor(chart_bg_hex)
                        except Exception:
                            pass
                    ax.plot(series, color=(primary_color or "#2563eb"))
                    ax.set_title(cat, fontsize=8, color=(text_hex or "#000000"))
                    ax.tick_params(colors=(text_hex or "#000000"))
                    for spine in ax.spines.values():
                        spine.set_color(text_hex or "#000000")
                    ax.set_xticks([]); ax.set_yticks([])
                    ax.grid(True, alpha=0.2)
                    img_b = io.BytesIO()
                    plt.tight_layout()
                    fig.savefig(img_b, format='png', dpi=150)
                    plt.close(fig)
                    img_b.seek(0)
                    col = i % cols
                    row = i // cols
                    x = x0 + col * (cell_w + 0.5*cm)
                    y_img = y0 - row * (cell_h + 0.5*cm)
                    if y_img - cell_h < bottom_m + 1.5*cm:
                        _show_page(); width, height = page_size; y_img = height - top_m - 1*cm; x0 = left; y0 = y_img
                        row = 0; col = 0; x = x0; y_img = y0
                    c.drawImage(img_b, x, y_img - cell_h, width=cell_w, height=cell_h, preserveAspectRatio=True, mask='auto')
                    i += 1
                y = y_img - cell_h - 0.8*cm
            except Exception:
                pass

        # Summary block
        c.setFont("Helvetica-Bold", 12.5)
        c.drawString(left, y, "Today's Summary:")
        y -= 0.6*cm
        c.setFont("Helvetica", 11)
        for line in simpleSplit(summary_text or "", "Helvetica", 11, width - 4*cm):
            c.drawString(left, y, line)
            y -= 0.5*cm
            if y < bottom_m + 2*cm:
                _show_page(); y = height - top_m

        # Tip block
        y -= 0.2*cm
        c.setFont("Helvetica-Bold", 12.5)
        c.drawString(left, y, "Personalized Tip:")
        y -= 0.6*cm
        c.setFont("Helvetica", 11)
        for line in simpleSplit(tip_text or "", "Helvetica", 11, width - 4*cm):
            c.drawString(left, y, line)
            y -= 0.5*cm
            if y < bottom_m + 2*cm:
                _show_page(); y = height - top_m

        # Per-category breakdown and pie chart (if provided)
        if per_category:
            y -= 0.2*cm
            c.setFont("Helvetica-Bold", 12)
            c.drawString(left, y, "Per-category (kg CO₂):")
            y -= 0.6*cm
            c.setFont("Helvetica", 11)
            for k, v in sorted(per_category.items(), key=lambda x: x[1], reverse=True):
                c.drawString(left, y, f"{k}: {float(v):.2f}")
                y -= 0.45*cm
                if y < bottom_m + 6*cm:
                    break
            if include_pie and mpl_ok:
                try:
                    fig, ax = plt.subplots(figsize=(4, 3))
                    labels = list(per_category.keys())
                    values = [float(v) for v in per_category.values()]
                    if sum(values) > 0:
                        if chart_bg_hex:
                            try:
                                fig.patch.set_facecolor(chart_bg_hex)
                                ax.set_facecolor(chart_bg_hex)
                            except Exception:
                                pass
                        ax.pie(values, labels=labels, autopct='%1.1f%%', startangle=140, textprops={'fontsize': 8, 'color': (text_hex or '#000000')}, colors=None)
                        for text in ax.texts:
                            text.set_color(text_hex or "#000000")
                        ax.axis('equal')
                        img_buf = io.BytesIO()
                        plt.tight_layout()
                        fig.savefig(img_buf, format='png', dpi=150)
                        plt.close(fig)
                        img_buf.seek(0)
                        img_width = 10*cm
                        img_height = 7*cm
                        c.drawImage(img_buf, right - img_width, y + 0.5*cm, width=img_width, height=img_height, preserveAspectRatio=True, mask='auto')
                        y -= img_height + 0.5*cm
                except Exception:
                    pass

        # Per-activity table (if provided)
        if per_activity:
            y -= 0.2*cm
            c.setFont("Helvetica-Bold", 12)
            c.drawString(left, y, "Per-activity emissions (kg CO₂):")
            y -= 0.6*cm
            c.setFont("Helvetica", 11)
            for k, v in sorted(per_activity.items(), key=lambda x: x[1], reverse=True):
                c.drawString(left, y, f"{k}: {float(v):.2f}")
                y -= 0.45*cm
                if y < bottom_m + 2*cm:
                    _show_page(); y = height - top_m

        _show_page()
        c.save()
        pdf_bytes = buf.getvalue()
        buf.close()
        return pdf_bytes, None
    except Exception as e:
        return None, f"Failed to build PDF: {e}"


if __name__ == "__main__":
    main()