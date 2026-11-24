"""
Day-ahead price forecasting for production planning (Week 3).

THE PLANNING SITUATION (decision D11)
Every day around noon the exchange publishes the prices for TOMORROW. A planner who makes the
production plan on day D therefore knows all prices up to day D+1, and needs a FORECAST for
days D+2 ... D+7 (horizon h = 2 ... 7 days).

GOLDEN RULE: every feature must be known at planning time. If we used information from after
the planning day (for example yesterday's price of the target day), the model would look great
in testing and fail in reality. This is called "data leakage".
"""
from __future__ import annotations

import holidays
import lightgbm as lgb
import numpy as np
import pandas as pd

import config

HORIZONS = range(2, 8)                     # forecast 2 ... 7 days ahead
QUARTERS = 96


# -----------------------------------------------------------------------------
# 1. Prices as a day x quarter-hour table
# -----------------------------------------------------------------------------
def price_matrix(prices: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (German) calendar day, 96 columns (00:00, 00:15, ... 23:45).
    Clock-change days: the doubled autumn hour is averaged; the missing spring hour is filled
    from the quarter-hour before (2 days per year, negligible).
    """
    local = pd.to_datetime(prices["timestamp_utc"], utc=True).dt.tz_convert(config.LOCAL_TZ)
    df = pd.DataFrame({
        "date": local.dt.date,
        "quarter": local.dt.hour * 4 + local.dt.minute // 15,
        "price": prices["price_eur_mwh"].to_numpy(),
    })
    m = df.pivot_table(index="date", columns="quarter", values="price", aggfunc="mean")
    m = m.reindex(columns=range(QUARTERS)).ffill(axis=1)
    m.index = pd.to_datetime(m.index)
    return m


# -----------------------------------------------------------------------------
# 2. Features that are known at planning time
# -----------------------------------------------------------------------------
def build_dataset(prices: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (target day T, horizon h, quarter q). The planning day is D = T - h,
    the last day with KNOWN prices is L = T - h + 1.
    """
    m = price_matrix(prices)
    days = m.index
    holi = holidays.Germany(subdiv="BW", years=sorted({d.year for d in days}))
    is_holiday = pd.Series([d in holi for d in days.date], index=days)

    mean7_q = m.rolling(7, min_periods=7).mean()              # per quarter, last 7 days up to L
    day_mean = m.mean(axis=1)
    mean7_day = day_mean.rolling(7, min_periods=7).mean()

    blocks = []
    q = np.arange(QUARTERS)
    for h in HORIZONS:
        for T in days:
            L = T - pd.Timedelta(days=h - 1)                   # last known day
            W = T - pd.Timedelta(days=7)                       # same weekday last week (known: h <= 7)
            if L not in m.index or W not in m.index or np.isnan(mean7_day.get(L, np.nan)):
                continue
            last = m.loc[L].to_numpy()
            blocks.append(pd.DataFrame({
                "target_date": T, "horizon": h, "quarter": q,
                # --- calendar of the target day (always known in advance)
                "hour": q // 4,
                "weekday": T.day_of_week,
                "month": T.month,
                "doy_sin": np.sin(2 * np.pi * T.day_of_year / 365.25),
                "doy_cos": np.cos(2 * np.pi * T.day_of_year / 365.25),
                "is_holiday": int(is_holiday.get(T, False)),
                "last_known_is_holiday": int(is_holiday.get(L, False)),
                # --- prices known at planning time
                "p_last_q": last,                                    # same quarter, last known day
                "p_last_shape": last - last.mean(),                  # daily shape of last known day
                "p_last_day_mean": last.mean(),
                "p_last_day_min": last.min(),
                "p_last_day_max": last.max(),
                "p_week_q": m.loc[W].to_numpy(),                     # same weekday & quarter last week
                "p_mean7_q": mean7_q.loc[L].to_numpy(),              # 7-day average of this quarter
                "p_mean7_day": mean7_day.loc[L],                     # 7-day average price level
                # --- what we want to predict
                "actual": m.loc[T].to_numpy(),
            }))
    return pd.concat(blocks, ignore_index=True)


FEATURES = ["horizon", "quarter", "hour", "weekday", "month", "doy_sin", "doy_cos", "is_holiday",
            "last_known_is_holiday", "p_last_q", "p_last_shape", "p_last_day_mean", "p_last_day_min",
            "p_last_day_max", "p_week_q", "p_mean7_q", "p_mean7_day"]

# Simple rules every model has to beat
BASELINES = {
    "Naive: last known day": "p_last_q",
    "Naive: same day last week": "p_week_q",
    "Naive: 7-day average": "p_mean7_q",
}

LGB_PARAMS = dict(objective="l1", n_estimators=600, learning_rate=0.03, num_leaves=31,
                  min_child_samples=50, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                  random_state=42, verbose=-1)


# -----------------------------------------------------------------------------
# 3. Honest testing: rolling-origin backtest (decision D12)
# -----------------------------------------------------------------------------
def rolling_backtest(data: pd.DataFrame, test_months: list[str]) -> tuple[pd.DataFrame, lgb.LGBMRegressor]:
    """
    For every test month: train ONLY on target days before that month, then forecast the month.
    This imitates using the model in real life, month after month, never seeing the future.
    """
    results = []
    model = None
    for month in test_months:
        start = pd.Timestamp(month + "-01")
        end = start + pd.offsets.MonthBegin(1)
        # Cut-off 7 days before the month: the first plan of the month (made up to 7 days earlier)
        # must not have been trained on prices that were unknown on that planning day.
        train = data[data["target_date"] < start - pd.Timedelta(days=7)]
        test = data[(data["target_date"] >= start) & (data["target_date"] < end)].copy()
        model = lgb.LGBMRegressor(**LGB_PARAMS).fit(train[FEATURES], train["actual"])
        test["LightGBM"] = model.predict(test[FEATURES])
        for name, col in BASELINES.items():
            test[name] = test[col]
        test["test_month"] = month
        results.append(test)
        print(f"  {month}: trained on {train['target_date'].nunique():>3} days, "
              f"tested on {test['target_date'].nunique()} days")
    return pd.concat(results, ignore_index=True), model


MODELS = ["LightGBM", *BASELINES]


def accuracy_table(results: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """MAE and RMSE (€/MWh) and the within-day ranking quality (Spearman) per model."""
    rows = []
    groups = results.groupby(by) if by else [(None, results)]
    for key, g in groups:
        for m in MODELS:
            err = g[m] - g["actual"]
            # ranking quality: does the forecast put the quarter-hours of each day in the right order?
            rank = (g.groupby(["target_date", "horizon"])[[m, "actual"]]
                    .apply(lambda d: d[m].corr(d["actual"], method="spearman")).mean())
            rows.append({by or "all": key, "model": m, "MAE": err.abs().mean(),
                         "RMSE": np.sqrt((err ** 2).mean()), "rank_corr": rank})
    out = pd.DataFrame(rows)
    return out.drop(columns="all") if by is None else out


# -----------------------------------------------------------------------------
# 4. Does a better forecast save more money? (decision value)
# -----------------------------------------------------------------------------
def decision_value(results: pd.DataFrame, aligned: pd.DataFrame, horizon: int,
                   models: list[str] | None = None) -> pd.DataFrame:
    """
    Plan every machine's PRODUCTION energy with each model's forecast (same-day shifting as in the
    Week 2 upper bound), but pay the ACTUAL prices. Compare with no shifting and with perfect knowledge.
    'captured_%' = share of the perfect-knowledge saving that the forecast achieves in reality.
    """
    import cost                                                   # local import avoids a cycle
    models = models or MODELS
    days = pd.to_datetime(results["target_date"].unique())
    local = aligned["timestamp_local"]
    sub = aligned[local.dt.tz_localize(None).dt.normalize().isin(days)].reset_index(drop=True)
    sub.attrs = aligned.attrs
    key = pd.DataFrame({"target_date": sub["timestamp_local"].dt.tz_localize(None).dt.normalize(),
                        "quarter": sub["timestamp_local"].dt.hour * 4 + sub["timestamp_local"].dt.minute // 15})
    fc_h = results[results["horizon"] == horizon][["target_date", "quarter", *models]]
    plans = key.merge(fc_h, on=["target_date", "quarter"], how="left")

    rows = {"No shifting": 0.0, "Perfect knowledge": 0.0, **{m: 0.0 for m in models}}
    for machine in aligned.attrs["machines"]:
        standby = cost.standby_kw(aligned, machine) / 4              # same split as Week 2 (full year)
        production = (sub[machine] - sub[machine].clip(upper=standby)).to_numpy()
        rows["No shifting"] += (production / 1000 * sub["price_eur_mwh"]).sum()
        rows["Perfect knowledge"] += cost.perfect_shift_cost(production, sub)
        for m in models:
            rows[m] += cost.perfect_shift_cost(production, sub, plan_price=plans[m].to_numpy())

    out = pd.DataFrame({"production_cost_eur": rows})
    out["saving_eur"] = out.loc["No shifting", "production_cost_eur"] - out["production_cost_eur"]
    out["captured_%"] = 100 * out["saving_eur"] / out.loc["Perfect knowledge", "saving_eur"]
    out.attrs["days"] = len(days)
    return out
