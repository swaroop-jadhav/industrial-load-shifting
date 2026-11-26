"""
Reusable cost calculations (notebook 02 baseline, reused in notebook 04 optimisation).

Approach:
The machine data is from 2024, the prices from Oct 2025 - Sep 2026. To "replay" the machines
against today's prices we match every price quarter-hour with the machine load from the
SAME week of the year, SAME weekday and SAME time of day in 2024 (assumption A5).
This keeps weekly rhythms (weekends, shifts) and seasons intact.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


# -----------------------------------------------------------------------------
# 1. Matching keys: (ISO week, weekday, quarter-hour of the day) in German local time
# -----------------------------------------------------------------------------
def calendar_key(ts_local: pd.Series) -> pd.DataFrame:
    iso = ts_local.dt.isocalendar()
    return pd.DataFrame({
        "week": iso["week"].astype(int).clip(upper=52),     # rare week 53 -> use week 52
        "weekday": ts_local.dt.day_of_week.astype(int),     # 0 = Monday
        "quarter": (ts_local.dt.hour * 4 + ts_local.dt.minute // 15).astype(int),
    }, index=ts_local.index)


def align_load_to_prices(loads: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """
    loads : long table  timestamp_utc | machine | energy_kwh   (2024)
    prices: table       timestamp_utc | price_eur_mwh           (price year)
    returns one row per price quarter-hour:
            timestamp_local | price_eur_mwh | <one energy_kwh column per machine>
    """
    loads = loads.copy()
    loads["timestamp_local"] = pd.to_datetime(loads["timestamp_utc"], utc=True).dt.tz_convert(config.LOCAL_TZ)
    loads = loads.join(calendar_key(loads["timestamp_local"]))

    # Assumption A6: fill measurement gaps with the machine's TYPICAL load for that weekday and
    # time of day (average over the whole year). Counting gaps as zero would understate the cost.
    typical = loads.groupby(["machine", "weekday", "quarter"])["energy_kwh"].transform("mean")
    gaps = loads["energy_kwh"].isna()
    loads["energy_kwh"] = loads["energy_kwh"].fillna(typical)
    # Clock-change days create duplicate keys -> average them
    by_key = loads.pivot_table(index=["week", "weekday", "quarter"], columns="machine",
                               values="energy_kwh", aggfunc="mean")

    out = prices[["timestamp_utc", "price_eur_mwh"]].copy()
    out["timestamp_local"] = pd.to_datetime(out["timestamp_utc"], utc=True).dt.tz_convert(config.LOCAL_TZ)
    out = out.join(calendar_key(out["timestamp_local"]))
    out = out.merge(by_key, left_on=["week", "weekday", "quarter"], right_index=True, how="left")

    machines = list(by_key.columns)
    out.attrs["gap_filled_share"] = float(gaps.mean())
    out.attrs["unmatched_share"] = float(out[machines].isna().all(axis=1).mean())
    out[machines] = out[machines].fillna(0)                 # nothing to match at all -> no load
    out.attrs["machines"] = machines
    return out.drop(columns=["week", "weekday", "quarter"]).reset_index(drop=True)


# -----------------------------------------------------------------------------
# 2. Baseline cost: what does the current schedule cost?
# -----------------------------------------------------------------------------
def baseline_cost(aligned: pd.DataFrame) -> pd.DataFrame:
    machines = aligned.attrs["machines"]
    price = aligned["price_eur_mwh"]
    rows = []
    for m in machines:
        kwh = aligned[m]
        mwh = kwh.sum() / 1000
        cost = (kwh / 1000 * price).sum()
        rows.append({"machine": m, "energy_mwh": mwh, "cost_eur": cost,
                     "price_paid_eur_mwh": cost / mwh if mwh > 0 else np.nan})
    table = pd.DataFrame(rows).set_index("machine").sort_values("cost_eur", ascending=False)
    total = pd.DataFrame({"energy_mwh": [table["energy_mwh"].sum()], "cost_eur": [table["cost_eur"].sum()]},
                         index=["TOTAL"])
    total["price_paid_eur_mwh"] = total["cost_eur"] / total["energy_mwh"]
    return pd.concat([table, total])


# -----------------------------------------------------------------------------
# 3. Standby vs. production energy
# -----------------------------------------------------------------------------
def standby_kw(aligned: pd.DataFrame, machine: str) -> float:
    """
    Standby (base) load = the machine's median power when the workshop is closed
    (weekends and 00:00-05:00). Controls, hydraulics, coolant pumps and cooling often keep running.
    This part cannot be shifted - only switched off (an efficiency measure, not load shifting).
    """
    local = aligned["timestamp_local"]
    closed = (local.dt.day_of_week >= 5) | (local.dt.hour < 5)
    return float(aligned.loc[closed, machine].median() * 4)          # kWh per 15 min -> kW


def split_standby(aligned: pd.DataFrame, machine: str) -> tuple[pd.Series, pd.Series]:
    """Split each quarter-hour's energy into standby part and production part (kWh)."""
    base_kwh = standby_kw(aligned, machine) / 4
    standby = aligned[machine].clip(upper=base_kwh)
    return standby, aligned[machine] - standby


# -----------------------------------------------------------------------------
# 4. Upper bound: the MOST that shifting within the same day could ever save
# -----------------------------------------------------------------------------
def perfect_shift_cost(kwh: np.ndarray, aligned: pd.DataFrame,
                       window_hours: tuple[int, int] = config.SHIFT_WINDOW_HOURS,
                       plan_price: np.ndarray | None = None) -> float:
    """
    For every day, take the (production) energy and place it into the cheapest quarter-hours of that
    same day - inside the shift window first - never above the highest observed energy per quarter-hour.
    This ignores job order, workers and process limits, so it is a CEILING for savings,
    not a realistic plan (that is notebook 04).

    plan_price: prices used to DECIDE where energy goes (e.g. a forecast). The cost is always paid
    at the ACTUAL price. Without plan_price we assume perfect knowledge of the actual prices.
    """
    kwh = np.asarray(kwh, dtype=float)
    price = aligned["price_eur_mwh"].to_numpy()
    rank = price if plan_price is None else np.asarray(plan_price, dtype=float)
    local = aligned["timestamp_local"]
    cap = kwh.max()                                     # max energy per quarter-hour (= peak kW x 0.25)
    if cap <= 0:
        return 0.0
    in_window = ((local.dt.hour >= window_hours[0]) & (local.dt.hour < window_hours[1])).to_numpy()
    day_codes = pd.factorize(local.dt.date)[0]

    total = 0.0
    for d in np.unique(day_codes):
        idx = np.flatnonzero(day_codes == d)
        energy = kwh[idx].sum()
        if energy <= 0:
            continue
        order = idx[np.lexsort((rank[idx], ~in_window[idx]))]    # window first, then cheapest (as planned)
        full_slots = int(energy // cap)
        total += cap * price[order[:full_slots]].sum()
        rest = energy - full_slots * cap
        if rest > 0 and full_slots < len(order):
            total += rest * price[order[full_slots]]
    return total / 1000                                    # kWh x €/MWh -> €


def savings_upper_bound(aligned: pd.DataFrame) -> pd.DataFrame:
    """Per machine: standby cost (not shiftable) and the maximum saving from shifting production energy."""
    price = aligned["price_eur_mwh"]
    rows = []
    for m in aligned.attrs["machines"]:
        standby, production = split_standby(aligned, m)
        production_cost = (production / 1000 * price).sum()
        shifted_cost = perfect_shift_cost(production.to_numpy(), aligned)
        rows.append({
            "machine": m,
            "standby_kw": standby_kw(aligned, m),
            "standby_mwh": standby.sum() / 1000,
            "standby_cost_eur": (standby / 1000 * price).sum(),
            "production_mwh": production.sum() / 1000,
            "production_cost_eur": production_cost,
            "max_saving_eur": production_cost - shifted_cost,
        })
    table = pd.DataFrame(rows).set_index("machine")
    table["max_saving_%_of_production"] = 100 * table["max_saving_eur"] / table["production_cost_eur"]
    table = table.sort_values("max_saving_eur", ascending=False)
    total = table.drop(columns=["standby_kw", "max_saving_%_of_production"]).sum().to_frame("TOTAL").T
    total["standby_kw"] = table["standby_kw"].sum()
    total["max_saving_%_of_production"] = 100 * total["max_saving_eur"] / total["production_cost_eur"]
    return pd.concat([table, total[table.columns]])
