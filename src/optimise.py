"""
Week 4: from the theoretical upper bound to a REALISTIC action plan.

What the data showed (Week 4, part A): the machines do not run as small jobs that can be moved
freely. They fall into three groups:
  - continuous  : runs for days without stopping (wire EDM)        -> cannot be shifted
  - shift-bound : one long block per working day (mills, lathes)   -> moves only if the SHIFT moves
  - cycling     : switches on/off every few minutes (coolers)      -> follows the workshop's heat load
So the realistic levers are: (1) switch standby off, (2) start the shift at a different time.

All costs use the 15-minute day x quarter-hour matrices from forecast.price_matrix().
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
import cost
import forecast as fc

QUARTERS = 96


# -----------------------------------------------------------------------------
# 1. How does each machine run?
# -----------------------------------------------------------------------------
def classify_machines(aligned: pd.DataFrame) -> pd.DataFrame:
    """Median length of a production run decides the type (decision D14)."""
    local = aligned["timestamp_local"]
    rows = []
    for m in aligned.attrs["machines"]:
        _, production = cost.split_standby(aligned, m)
        kw = production * 4
        on = kw > 0.1 * kw.quantile(0.95)                     # "running" = above 10% of its typical peak
        run_id = (on != on.shift()).cumsum()
        runs = on[on].groupby(run_id[on]).size() * 0.25       # run lengths in hours
        median_h = float(runs.median()) if len(runs) else 0.0
        kind = "continuous" if median_h > 24 else ("cycling" if median_h < 2 else "shift-bound")
        rows.append({"machine": m, "production_mwh": production.sum() / 1000, "runs": len(runs),
                     "median_run_h": median_h,
                     "weekend_share_%": 100 * production[local.dt.day_of_week >= 5].sum() / max(production.sum(), 1e-9),
                     "type": kind})
    return pd.DataFrame(rows).set_index("machine").sort_values("production_mwh", ascending=False)


# -----------------------------------------------------------------------------
# 2. Day x quarter-hour matrices (same layout as forecast.price_matrix)
# -----------------------------------------------------------------------------
def day_matrix(values: pd.Series, aligned: pd.DataFrame) -> pd.DataFrame:
    local = aligned["timestamp_local"]
    df = pd.DataFrame({"date": local.dt.tz_localize(None).dt.normalize(),
                       "quarter": local.dt.hour * 4 + local.dt.minute // 15,
                       "value": np.asarray(values, dtype=float)})
    m = df.pivot_table(index="date", columns="quarter", values="value", aggfunc="sum")
    return m.reindex(columns=range(QUARTERS)).fillna(0.0)


def production_matrix(aligned: pd.DataFrame, machines: list[str]) -> pd.DataFrame:
    total = None
    for m in machines:
        _, production = cost.split_standby(aligned, m)
        mat = day_matrix(production, aligned)
        total = mat if total is None else total.add(mat, fill_value=0)
    return total


def matrix_cost(energy_kwh: pd.DataFrame, price: pd.DataFrame) -> pd.Series:
    """€ per day = sum over quarter-hours of kWh x €/MWh / 1000."""
    p = price.reindex(index=energy_kwh.index, columns=energy_kwh.columns)
    return (energy_kwh * p).sum(axis=1) / 1000


# -----------------------------------------------------------------------------
# 3. Lever 2: move the shift by whole hours (weekdays only)
# -----------------------------------------------------------------------------
def shift_rows(energy: np.ndarray, hours: int) -> np.ndarray:
    """Move each day's load profile by `hours` (positive = later). Energy that would fall past
    the end/start of the day stays in the last/first quarter-hour, so no energy is lost."""
    k = 4 * hours
    out = np.zeros_like(energy)
    if k > 0:
        out[:, k:] = energy[:, :-k]
        out[:, -1] += energy[:, -k:].sum(axis=1)
    elif k < 0:
        out[:, :k] = energy[:, -k:]
        out[:, 0] += energy[:, :-k].sum(axis=1)
    else:
        out = energy.copy()
    return out


def apply_offsets(energy: pd.DataFrame, offsets: pd.Series) -> pd.DataFrame:
    """offsets: hours per date (0 for weekends / days that are not moved)."""
    out = energy.to_numpy().copy()
    for h in np.unique(offsets.to_numpy()):
        if h == 0:
            continue
        rows = np.flatnonzero(offsets.to_numpy() == h)
        out[rows] = shift_rows(energy.to_numpy()[rows], int(h))
    return pd.DataFrame(out, index=energy.index, columns=energy.columns)


def offset_table(energy: pd.DataFrame, price: pd.DataFrame, hours=range(-2, 7)) -> pd.DataFrame:
    """Saving (€) per month for every fixed shift offset applied to all weekdays."""
    weekday = pd.Series(energy.index.day_of_week < 5, index=energy.index)
    base = matrix_cost(energy, price)
    month = energy.index.strftime("%Y-%m")
    cols = {}
    for h in hours:
        offs = pd.Series(np.where(weekday, h, 0), index=energy.index)
        cols[h] = (base - matrix_cost(apply_offsets(energy, offs), price)).groupby(month).sum()
    return pd.DataFrame(cols)


def seasonal_offsets(index: pd.DatetimeIndex, summer_hours: int, summer_months=range(4, 10)) -> pd.Series:
    """Summer schedule: weekdays in Apr-Sep start `summer_hours` later, the rest stays as is."""
    move = (index.day_of_week < 5) & index.month.isin(list(summer_months))
    return pd.Series(np.where(move, summer_hours, 0), index=index)


def weekly_forecast_offsets(energy: pd.DataFrame, prices: pd.DataFrame,
                            options=range(0, 5)) -> pd.Series:
    """
    Every Friday (after the noon auction) the planner picks ONE shift start for the next Mon-Fri,
    using the 7-day-average forecast (decision D13). Monday is then 3 days ahead ... Friday 7 days.
    Options: 0 to +4 hours later than today (never earlier - the shift already starts at 04:00-05:00).
    Weeks without a forecast (first week of data) keep the normal shift.
    """
    data = fc.build_dataset(prices)
    data["forecast"] = data["p_mean7_q"]
    weekday = energy.index.day_of_week
    offsets = pd.Series(0, index=energy.index)
    mondays = energy.index[weekday == 0]
    for monday in mondays:
        days = [monday + pd.Timedelta(days=i) for i in range(5) if monday + pd.Timedelta(days=i) in energy.index]
        fc_rows = []
        for i, d in enumerate(days):
            f = data[(data["target_date"] == d) & (data["horizon"] == 3 + i)].sort_values("quarter")
            if len(f) != QUARTERS:
                break
            fc_rows.append(f["forecast"].to_numpy())
        if len(fc_rows) != len(days) or not days:
            continue
        fmat = np.vstack(fc_rows)
        e = energy.loc[days].to_numpy()
        costs = {h: (shift_rows(e, h) * fmat).sum() for h in options}
        offsets.loc[days] = min(costs, key=costs.get)
    return offsets


def perfect_weekly_offsets(energy: pd.DataFrame, price: pd.DataFrame, options=range(0, 5)) -> pd.Series:
    """Same weekly choice, but with perfect knowledge of the actual prices (upper bound for this rule)."""
    weekday = energy.index.day_of_week
    p = price.reindex(index=energy.index)
    offsets = pd.Series(0, index=energy.index)
    for monday in energy.index[weekday == 0]:
        days = [monday + pd.Timedelta(days=i) for i in range(5) if monday + pd.Timedelta(days=i) in energy.index]
        e, pm = energy.loc[days].to_numpy(), p.loc[days].to_numpy()
        costs = {h: (shift_rows(e, h) * pm).sum() for h in options}
        offsets.loc[days] = min(costs, key=costs.get)
    return offsets


# -----------------------------------------------------------------------------
# 4. Lever 1: switch standby off outside working hours
# -----------------------------------------------------------------------------
def standby_off_saving(aligned: pd.DataFrame, machine: str,
                       keep_on_hours: tuple[int, int] = (3, 17),
                       shift_offsets: pd.Series | None = None) -> dict:
    """
    Standby stays ON on weekdays between keep_on_hours (1 h warm-up before the earliest shift start
    at 04:00, buffer after the shift); outside that it is switched OFF. Returns energy and € saved.
    shift_offsets (hours per date): if the shift moves later, the keep-on window moves with it.
    """
    standby, _ = cost.split_standby(aligned, machine)
    local = aligned["timestamp_local"]
    move = 0
    if shift_offsets is not None:
        dates = local.dt.tz_localize(None).dt.normalize()
        move = dates.map(shift_offsets).fillna(0).to_numpy()
    start, end = keep_on_hours[0] + move, keep_on_hours[1] + move
    on = (local.dt.day_of_week < 5) & (local.dt.hour >= start) & (local.dt.hour < end)
    removed = standby.where(~on, 0.0)
    return {"machine": machine, "standby_kw": cost.standby_kw(aligned, machine),
            "saved_mwh": removed.sum() / 1000,
            "saved_eur": (removed / 1000 * aligned["price_eur_mwh"]).sum()}
