"""
Industrial Load Shifting - dashboard for the plant manager (Week 5).

Run locally (from the project folder):
    streamlit run dashboard/app.py
All numbers come from dashboard/data/*.csv, written by `python src/results.py`.
"""
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

DATA = Path(__file__).parent / "data"
BLUE, ORANGE, GREEN, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#898781"
SUMMER = ["04", "05", "06", "07", "08", "09"]

st.set_page_config(page_title="Industrial Load Shifting", page_icon="⚡", layout="wide")


@st.cache_data
def load(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA / f"{name}.csv")


def euro(x: float) -> str:
    return f"−€{abs(x):,.0f}" if x < 0 else f"€{x:,.0f}"


kpi = load("kpis").iloc[0]
levers, machines = load("levers"), load("machines")
hourly, monthly = load("hourly_profile"), load("monthly")
rhythm, heat = load("weekly_rhythm"), load("shift_heatmap")

# ----------------------------------------------------------------------------- header
st.title("⚡ Cutting a CNC workshop's electricity cost")
st.caption("11 machines of a real workshop (KIT SPARK data, 2024) replayed against German 15-minute "
           "day-ahead prices, Oct 2025 – Sep 2026. Wholesale electricity only.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Electricity cost today", euro(kpi.baseline_cost_eur))
c1.caption(f"{kpi.energy_mwh:,.0f} MWh per year, wholesale price")
c2.metric("Recommended saving", euro(kpi.recommended_saving_eur), f"{kpi.recommended_saving_pct:.0f}% of the bill")
c3.metric("CO₂ saved", f"{kpi.recommended_co2_saved_t:,.1f} t", f"{kpi.recommended_co2_saved_pct:.0f}% of emissions")
c4.metric("Energy used as standby", f"{kpi.standby_share_pct:.0f}%")
c4.caption(f"{euro(kpi.standby_cost_eur)} per year while nothing is produced")

tab_plan, tab_machines, tab_time, tab_shift, tab_fc = st.tabs(
    ["Action plan", "Machines", "Cheap & clean hours", "Shift timing", "Price forecast"])

# ----------------------------------------------------------------------------- action plan
with tab_plan:
    st.subheader("What the workshop can actually do")
    st.markdown(
        f"The theoretical maximum for moving energy to cheaper hours is **{euro(kpi.upper_bound_shift_eur)}**, "
        "but the machines cannot be moved freely: the wire EDM runs for days, and the mills run one block per shift. "
        f"The biggest lever is **standby**: {kpi.standby_share_pct:.0f}% of all energy is used while nothing is produced.")
    plan = levers.copy()
    plan["colour"] = plan["status"].map({"recommended": BLUE, "alternative to 2": GREY, "theoretical": "#c3c2bd"})
    bars = alt.Chart(plan).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("saving_eur:Q", title="€ per year",
                scale=alt.Scale(domain=[0, float(plan["saving_eur"].max()) * 1.12])),
        y=alt.Y("lever:N", sort=None, title=None, axis=alt.Axis(labelLimit=320),
                scale=alt.Scale(paddingInner=0.35)),
        color=alt.Color("colour:N", scale=None),
        tooltip=[alt.Tooltip("lever:N", title="Lever"), alt.Tooltip("saving_eur:Q", title="€ per year", format=",.0f"),
                 alt.Tooltip("co2_saved_t:Q", title="t CO₂ saved", format=".1f"), alt.Tooltip("status:N")])
    labels = bars.mark_text(align="left", dx=4, fontSize=12).encode(      # mid grey: readable in light and dark mode
        text=alt.Text("saving_eur:Q", format=",.0f"), color=alt.value(GREY))
    st.altair_chart((bars + labels).properties(height=220), width="stretch")
    st.caption("Blue = recommended (1 + 2), grey = alternative to lever 2, light grey = theoretical upper bound.")
    table = levers.assign(
        saving_eur=levers["saving_eur"].map(euro),
        co2_saved_t=levers["co2_saved_t"].map(lambda v: "–" if pd.isna(v) else f"{v:.1f} t"))
    st.dataframe(table.rename(columns={"saving_eur": "€ per year", "co2_saved_t": "CO₂ saved",
                                       "check_first": "check first"}), hide_index=True, width="stretch")

# ----------------------------------------------------------------------------- machines
with tab_machines:
    st.subheader("Where the money goes")
    split = machines[["machine", "standby_cost_eur", "cost_eur"]].copy()
    split["production_cost_eur"] = split["cost_eur"] - split["standby_cost_eur"]
    split = split.melt(id_vars="machine", value_vars=["production_cost_eur", "standby_cost_eur"],
                       var_name="part", value_name="eur")
    split["part"] = split["part"].map({"production_cost_eur": "Production", "standby_cost_eur": "Standby"})
    order = machines.sort_values("cost_eur", ascending=False)["machine"].tolist()
    chart = alt.Chart(split).mark_bar(stroke="white", strokeWidth=2).encode(
        x=alt.X("eur:Q", title="€ per year", stack=True),
        y=alt.Y("machine:N", sort=order, title=None, axis=alt.Axis(labelLimit=260),
                scale=alt.Scale(paddingInner=0.3)),
        color=alt.Color("part:N", scale=alt.Scale(domain=["Production", "Standby"], range=[BLUE, ORANGE]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=["machine:N", "part:N", alt.Tooltip("eur:Q", format=",.0f", title="€ per year")])
    st.altair_chart(chart.properties(height=34 * len(order)), width="stretch")

    st.subheader("When the workshop runs")
    order_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hm = alt.Chart(rhythm).mark_rect().encode(
        x=alt.X("hour:O", title="Hour of day"), y=alt.Y("weekday_name:N", sort=order_days, title=None),
        color=alt.Color("kw:Q", scale=alt.Scale(scheme="blues"), title="Avg kW"),
        tooltip=["weekday_name:N", "hour:O", alt.Tooltip("kw:Q", format=".1f", title="Average kW")])
    st.altair_chart(hm.properties(height=230), width="stretch")

    show = machines[["machine", "type", "energy_mwh", "cost_eur", "price_paid_eur_mwh", "standby_kw",
                     "standby_cost_eur", "standby_off_saving_eur", "co2_t"]]
    st.dataframe(show, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.1f") for c in show.columns[2:]})

# ----------------------------------------------------------------------------- time of day
with tab_time:
    st.subheader("Cheap hours are clean hours")
    st.markdown("Around midday, solar power pushes both the **price** and the **CO₂ per kWh** down — "
                "especially from April to September. The workshop's shift (≈ 05:00–15:00) starts in the "
                "expensive morning peak.")
    season_scale = alt.Scale(domain=["Summer (Apr-Sep)", "Winter (Oct-Mar)"], range=[ORANGE, BLUE])
    base_line = alt.Chart(hourly).encode(x=alt.X("hour:Q", title="Hour of day", scale=alt.Scale(domain=[0, 23])),
                                         color=alt.Color("season:N", scale=season_scale,
                                                         legend=alt.Legend(title=None, orient="top")))
    left, right = st.columns(2)
    left.altair_chart(base_line.mark_line(strokeWidth=2, point=True).encode(
        y=alt.Y("avg_price_eur_mwh:Q", title="Average price (€/MWh)"),
        tooltip=["season:N", "hour:Q", alt.Tooltip("avg_price_eur_mwh:Q", format=".0f", title="€/MWh")]
    ).properties(title="Electricity price", height=300), width="stretch")
    right.altair_chart(base_line.mark_line(strokeWidth=2, point=True).encode(
        y=alt.Y("avg_co2_g_kwh:Q", title="g CO₂ per kWh"),
        tooltip=["season:N", "hour:Q", alt.Tooltip("avg_co2_g_kwh:Q", format=".0f", title="g CO₂/kWh")]
    ).properties(title="CO₂ intensity of grid electricity", height=300), width="stretch")

    energy_hour = hourly.groupby("hour", as_index=False)["workshop_energy_mwh"].sum()
    st.altair_chart(alt.Chart(energy_hour).mark_bar(color=BLUE, cornerRadiusEnd=3).encode(
        x=alt.X("hour:O", title="Hour of day"), y=alt.Y("workshop_energy_mwh:Q", title="MWh per year"),
        tooltip=["hour:O", alt.Tooltip("workshop_energy_mwh:Q", format=".1f", title="MWh")]
    ).properties(title="Workshop energy use by hour (whole year)", height=240), width="stretch")

# ----------------------------------------------------------------------------- shift timing
with tab_shift:
    st.subheader("Try it: move the summer shift")
    hours = st.slider("Shift starts this many hours later from April to September", 0, 6, 4)
    heat["month_num"] = heat["month"].str[-2:]
    pick = heat[(heat["shift_hours"] == hours) & heat["month_num"].isin(SUMMER)]
    winter = heat[(heat["shift_hours"] == hours) & ~heat["month_num"].isin(SUMMER)]
    a, b = st.columns(2)
    a.metric("Saving with a summer schedule", euro(pick["saving_eur"].sum()) + " per year")
    b.metric("If the same shift were also used in winter", euro(winter["saving_eur"].sum()) + " per year",
             help="Negative = extra cost. In winter there is no midday solar dip, so a later shift costs more.")
    st.caption("Movable energy = all machines except the wire EDM, which runs continuously for days.")

    heat["label"] = heat["shift_hours"].map(lambda h: f"{h:+d} h")
    lim = float(heat["saving_eur"].abs().max())
    rect = alt.Chart(heat).mark_rect().encode(
        x=alt.X("label:N", sort=[f"{h:+d} h" for h in range(-2, 7)], title="Shift moved by"),
        y=alt.Y("month:N", title=None),
        color=alt.Color("saving_eur:Q", title="€ saved",
                        scale=alt.Scale(domain=[-lim, 0, lim], range=[ORANGE, "#f0efec", BLUE], interpolate="rgb")),
        tooltip=["month:N", "label:N", alt.Tooltip("saving_eur:Q", format=",.0f", title="€ saved")])
    text = rect.mark_text(fontSize=11).encode(text=alt.Text("saving_eur:Q", format=".0f"),
                                              color=alt.value("#0b0b0b"))
    st.altair_chart((rect + text).properties(height=400,
                    title="€ saved per month by moving the weekday shift (orange = extra cost)"),
                    width="stretch")

# ----------------------------------------------------------------------------- forecast
with tab_fc:
    fc_path = DATA / "forecast.csv"
    if fc_path.exists():
        fc = load("forecast").sort_values("MAE")
        st.subheader("Do we need machine learning to plan?")
        st.markdown("Planning a week ahead needs a **forecast** of prices 2–7 days out. A simple 7-day average "
                    "was as accurate as LightGBM — and captured more of the possible saving, because ranking the "
                    "hours of a day correctly matters more than the exact price.")
        l, r = st.columns(2)
        y_model = alt.Y("model:N", sort=None, title=None, axis=alt.Axis(labelLimit=220),
                        scale=alt.Scale(paddingInner=0.35))
        l.altair_chart(alt.Chart(fc).mark_bar(color=BLUE, cornerRadiusEnd=3).encode(
            x=alt.X("MAE:Q", title="Average error (€/MWh, lower is better)"), y=y_model,
            tooltip=["model:N", alt.Tooltip("MAE:Q", format=".1f")]).properties(height=190, title="Forecast error"),
            width="stretch")
        r.altair_chart(alt.Chart(fc).mark_bar(color=GREEN, cornerRadiusEnd=3).encode(
            x=alt.X("captured_pct_7_days_ahead:Q", title="% of the perfect-knowledge saving",
                    scale=alt.Scale(domain=[0, 100])),
            y=y_model,
            tooltip=["model:N", alt.Tooltip("captured_pct_7_days_ahead:Q", format=".1f", title="% captured")]
        ).properties(height=200, title="Saving captured (planning 7 days ahead)"), width="stretch")
    else:
        st.info("Forecast results not exported yet.")

# ----------------------------------------------------------------------------- footer
with st.sidebar:
    st.markdown("### About")
    st.markdown(
        "Portfolio project by **Swaroop Jadhav** (MSc Machine Learning & Data Analytics, HS Aalen).\n\n"
        "[Code and notebooks on GitHub](https://github.com/swaroop-jadhav/industrial-load-shifting)")
    st.markdown("### Data")
    st.markdown("- Prices: Bundesnetzagentur / SMARD.de via Energy-Charts (Fraunhofer ISE), CC BY 4.0\n"
                "- Generation mix for CO₂: Energy-Charts (Fraunhofer ISE), CC BY 4.0\n"
                "- Machines: SPARK, KIT Karlsruhe (2026), CC BY 4.0")
    st.markdown("### Read with care")
    st.markdown("Wholesale price only (grid fees and taxes come on top). CO₂ uses average life-cycle emission "
                "factors of German generation — good for comparing schedules, not an official footprint. "
                "Standby switch-off must be confirmed with the machine operators.")
