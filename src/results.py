"""
All final results in small, tidy tables (Week 5).

Used by notebook 05 AND by the dashboards (Streamlit and Power BI), so every number shown anywhere
comes from the same calculation. Run `python src/results.py` to (re)write dashboard/data/*.csv.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import co2
import config
import cost
import forecast as fc
import optimise as op

SUMMER_SHIFT_HOURS = 4                     # decision D16


def build_tables(loads: pd.DataFrame, prices: pd.DataFrame, generation: pd.DataFrame,
                 with_forecast: bool = True) -> dict[str, pd.DataFrame]:
    aligned = cost.align_load_to_prices(loads, prices)
    machines = aligned.attrs["machines"]
    labels = config.SPARK_MACHINES
    intensity = co2.intensity(generation)
    ci_matrix = co2.intensity_matrix(intensity)
    price_m = fc.price_matrix(prices)

    # ---------------- baseline, standby, upper bound (Week 2) ----------------
    base = cost.baseline_cost(aligned)
    bound = cost.savings_upper_bound(aligned)
    market_avg = aligned["price_eur_mwh"].mean()

    # ---------------- levers (Week 4) ----------------
    classes = op.classify_machines(aligned)
    movable = classes.index[classes["type"] != "continuous"].tolist()
    energy = op.production_matrix(aligned, movable)
    summer = op.seasonal_offsets(energy.index, SUMMER_SHIFT_HOURS)
    shifted = op.apply_offsets(energy, summer)
    lever2_eur = op.matrix_cost(energy, price_m).sum() - op.matrix_cost(shifted, price_m).sum()
    lever2_co2 = co2.emissions_t(energy, ci_matrix) - co2.emissions_t(shifted, ci_matrix)

    weekly = op.weekly_forecast_offsets(energy, prices)
    weekly_shifted = op.apply_offsets(energy, weekly)
    lever3_eur = op.matrix_cost(energy, price_m).sum() - op.matrix_cost(weekly_shifted, price_m).sum()
    lever3_co2 = co2.emissions_t(energy, ci_matrix) - co2.emissions_t(weekly_shifted, ci_matrix)

    lever1 = {}
    for m in machines:
        removed = op.standby_removed_kwh(aligned, m, shift_offsets=summer)
        lever1[m] = {"eur": float((removed / 1000 * aligned["price_eur_mwh"]).sum()),
                     "mwh": removed.sum() / 1000,
                     "co2_t": co2.emissions_series_t(removed, aligned, intensity)}
    lever1_eur = sum(v["eur"] for v in lever1.values())
    lever1_co2 = sum(v["co2_t"] for v in lever1.values())

    # ---------------- per machine ----------------
    machine_rows = []
    for m in machines:
        machine_rows.append({
            "machine": labels.get(m, m), "machine_id": m, "type": classes.loc[m, "type"],
            "energy_mwh": base.loc[m, "energy_mwh"], "cost_eur": base.loc[m, "cost_eur"],
            "price_paid_eur_mwh": base.loc[m, "price_paid_eur_mwh"],
            "standby_kw": bound.loc[m, "standby_kw"], "standby_mwh": bound.loc[m, "standby_mwh"],
            "standby_cost_eur": bound.loc[m, "standby_cost_eur"],
            "production_mwh": bound.loc[m, "production_mwh"],
            "upper_bound_saving_eur": bound.loc[m, "max_saving_eur"],
            "standby_off_saving_eur": lever1[m]["eur"],
            "co2_t": co2.emissions_series_t(aligned[m], aligned, intensity),
        })
    machine_table = pd.DataFrame(machine_rows).sort_values("cost_eur", ascending=False)

    # ---------------- KPIs ----------------
    baseline_eur = base.loc["TOTAL", "cost_eur"]
    baseline_co2 = machine_table["co2_t"].sum()
    kpis = pd.DataFrame([{
        "baseline_cost_eur": baseline_eur,
        "energy_mwh": base.loc["TOTAL", "energy_mwh"],
        "price_paid_eur_mwh": base.loc["TOTAL", "price_paid_eur_mwh"],
        "market_avg_eur_mwh": market_avg,
        "standby_share_pct": 100 * bound.loc["TOTAL", "standby_mwh"] / base.loc["TOTAL", "energy_mwh"],
        "standby_cost_eur": bound.loc["TOTAL", "standby_cost_eur"],
        "upper_bound_shift_eur": bound.loc["TOTAL", "max_saving_eur"],
        "lever1_standby_off_eur": lever1_eur,
        "lever2_summer_shift_eur": lever2_eur,
        "lever3_weekly_plan_eur": lever3_eur,
        "recommended_saving_eur": lever1_eur + lever2_eur,
        "recommended_saving_pct": 100 * (lever1_eur + lever2_eur) / baseline_eur,
        "baseline_co2_t": baseline_co2,
        "recommended_co2_saved_t": lever1_co2 + lever2_co2,
        "recommended_co2_saved_pct": 100 * (lever1_co2 + lever2_co2) / baseline_co2,
        "grid_co2_avg_g_kwh": intensity["co2_g_per_kwh"].mean(),
    }])

    levers = pd.DataFrame([
        {"lever": "1. Standby off outside working hours", "saving_eur": lever1_eur, "co2_saved_t": lever1_co2,
         "status": "recommended", "effort": "low", "check_first": "why machines stay on (warm-up, accuracy)"},
        {"lever": f"2. Summer schedule: Apr-Sep shift +{SUMMER_SHIFT_HOURS} h", "saving_eur": lever2_eur,
         "co2_saved_t": lever2_co2, "status": "recommended", "effort": "medium",
         "check_first": "working-time rules, workers' preferences"},
        {"lever": "3. Weekly shift plan with forecast", "saving_eur": lever3_eur, "co2_saved_t": lever3_co2,
         "status": "alternative to 2", "effort": "high", "check_first": "changing hours every week"},
        {"lever": "Upper bound: free same-day shifting (theory)", "saving_eur": bound.loc["TOTAL", "max_saving_eur"],
         "co2_saved_t": np.nan, "status": "theoretical", "effort": "-", "check_first": "-"},
    ])

    # ---------------- profiles ----------------
    a = aligned.copy()
    a["total_kwh"] = a[machines].sum(axis=1)
    a["cost_eur"] = a["total_kwh"] / 1000 * a["price_eur_mwh"]
    a = a.merge(intensity, on="timestamp_utc", how="left")
    a["co2_kg"] = a["total_kwh"] * a["co2_g_per_kwh"] / 1000
    a["hour"] = a["timestamp_local"].dt.hour
    a["month"] = a["timestamp_local"].dt.strftime("%Y-%m")
    a["season"] = np.where(a["timestamp_local"].dt.month.isin(range(4, 10)), "Summer (Apr-Sep)", "Winter (Oct-Mar)")

    hourly = a.groupby(["season", "hour"]).agg(
        avg_price_eur_mwh=("price_eur_mwh", "mean"), avg_co2_g_kwh=("co2_g_per_kwh", "mean"),
        workshop_energy_mwh=("total_kwh", lambda s: s.sum() / 1000), workshop_cost_eur=("cost_eur", "sum"),
    ).reset_index()

    monthly = a.groupby("month").agg(
        energy_mwh=("total_kwh", lambda s: s.sum() / 1000), cost_eur=("cost_eur", "sum"),
        co2_t=("co2_kg", lambda s: s.sum() / 1000), avg_price_eur_mwh=("price_eur_mwh", "mean"),
        avg_co2_g_kwh=("co2_g_per_kwh", "mean"),
    ).reset_index()
    monthly["price_paid_eur_mwh"] = monthly["cost_eur"] / monthly["energy_mwh"]
    m_idx = energy.index.strftime("%Y-%m")
    monthly = monthly.merge(
        (op.matrix_cost(energy, price_m) - op.matrix_cost(shifted, price_m)).groupby(m_idx).sum()
        .rename("summer_shift_saving_eur").rename_axis("month").reset_index(), on="month", how="left")

    rhythm = loads.assign(local=loads["timestamp_utc"].dt.tz_convert(config.LOCAL_TZ))
    rhythm = rhythm.groupby("local")["avg_kw"].sum().to_frame("kw")
    rhythm = (rhythm.groupby([rhythm.index.day_of_week, rhythm.index.hour])["kw"].mean()
              .rename_axis(["weekday", "hour"]).reset_index())
    rhythm["weekday_name"] = rhythm["weekday"].map(dict(enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])))

    heat = op.offset_table(energy, price_m, hours=range(-2, 7))
    shift_heatmap = (heat.rename_axis("month").reset_index()
                     .melt(id_vars="month", var_name="shift_hours", value_name="saving_eur"))

    tables = {"kpis": kpis, "levers": levers, "machines": machine_table, "hourly_profile": hourly,
              "monthly": monthly, "weekly_rhythm": rhythm, "shift_heatmap": shift_heatmap}

    # ---------------- forecast comparison (Week 3) ----------------
    if with_forecast:
        data = fc.build_dataset(prices)
        results, _ = fc.rolling_backtest(data, [f"2026-{m:02d}" for m in range(3, 10)])
        acc = fc.accuracy_table(results).set_index("model")
        dv = fc.decision_value(results, aligned, horizon=7)
        acc["captured_pct_7_days_ahead"] = dv["captured_%"].reindex(acc.index)
        tables["forecast"] = acc.reset_index()
    return tables


def export(tables: dict[str, pd.DataFrame], folder=config.DASHBOARD_DATA_DIR) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.round(4).to_csv(folder / f"{name}.csv", index=False)
    print(f"Saved {len(tables)} tables -> {folder}")


if __name__ == "__main__":
    loads = pd.read_csv(config.SPARK_LOAD_FILE, parse_dates=["timestamp_utc"])
    prices = pd.read_csv(config.PRICES_RAW_FILE, parse_dates=["timestamp_utc"])
    generation = pd.read_csv(config.GENERATION_FILE, parse_dates=["timestamp_utc"])
    export(build_tables(loads, prices, generation))
