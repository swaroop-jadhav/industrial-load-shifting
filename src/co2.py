"""
CO2 intensity of German grid electricity per quarter-hour (Week 5).

METHOD (assumption A10): generation-based AVERAGE emission factor
    intensity [g CO2-eq/kWh] = sum(generation_source x factor_source) / sum(generation_source)
using German generation only (imports/exports and pumped storage are left out, because pumped
storage only moves energy that was generated earlier, and imports have their own mix).

Emission factors are life-cycle values in g CO2-eq per kWh, based on the IPCC AR5 (2014) medians
where available, and typical German values for lignite and other fuels. They are approximations:
use the results to COMPARE schedules, not as an official carbon footprint.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

EMISSION_FACTORS = {                    # g CO2-eq per kWh generated
    "fossil_brown_coal_lignite": 1100,
    "fossil_hard_coal": 820,
    "fossil_coal_derived_gas": 1000,
    "fossil_oil": 650,
    "fossil_gas": 490,
    "waste": 300,
    "others": 400,
    "biomass": 230,
    "geothermal": 38,
    "hydro_run_of_river": 24,
    "hydro_water_reservoir": 24,
    "solar": 45,
    "wind_onshore": 11,
    "wind_offshore": 12,
    "nuclear": 12,
}


def intensity(generation: pd.DataFrame) -> pd.DataFrame:
    """Returns timestamp_utc | co2_g_per_kwh | renewable_share_% (of the sources used)."""
    sources = [s for s in EMISSION_FACTORS if s in generation.columns]
    gen = generation[sources].clip(lower=0).fillna(0)
    total = gen.sum(axis=1)
    weighted = sum(gen[s] * EMISSION_FACTORS[s] for s in sources)
    renewable = [s for s in sources if s in ("biomass", "geothermal", "hydro_run_of_river",
                                             "hydro_water_reservoir", "solar", "wind_onshore", "wind_offshore")]
    out = pd.DataFrame({
        "timestamp_utc": pd.to_datetime(generation["timestamp_utc"], utc=True),
        "co2_g_per_kwh": (weighted / total.where(total > 0)).to_numpy(),
        "renewable_share_%": (100 * gen[renewable].sum(axis=1) / total.where(total > 0)).to_numpy(),
    })
    return out


def intensity_matrix(co2: pd.DataFrame) -> pd.DataFrame:
    """Day x quarter-hour table, same layout as forecast.price_matrix (g CO2-eq per kWh)."""
    local = co2["timestamp_utc"].dt.tz_convert(config.LOCAL_TZ)
    df = pd.DataFrame({"date": local.dt.tz_localize(None).dt.normalize(),
                       "quarter": local.dt.hour * 4 + local.dt.minute // 15,
                       "value": co2["co2_g_per_kwh"].to_numpy()})
    m = df.pivot_table(index="date", columns="quarter", values="value", aggfunc="mean")
    return m.reindex(columns=range(96)).ffill(axis=1).bfill(axis=1)


def emissions_t(energy_kwh: pd.DataFrame, co2_matrix: pd.DataFrame) -> float:
    """Tonnes CO2-eq = sum(kWh x g/kWh) / 1e6 for a day x quarter-hour energy table."""
    c = co2_matrix.reindex(index=energy_kwh.index, columns=energy_kwh.columns)
    return float(np.nansum(energy_kwh.to_numpy() * c.to_numpy()) / 1e6)


def emissions_series_t(kwh: pd.Series, aligned: pd.DataFrame, co2: pd.DataFrame) -> float:
    """Tonnes CO2-eq for a quarter-hour energy series that is row-aligned with `aligned`."""
    merged = aligned[["timestamp_utc"]].merge(co2[["timestamp_utc", "co2_g_per_kwh"]],
                                              on="timestamp_utc", how="left")
    g = merged["co2_g_per_kwh"].fillna(merged["co2_g_per_kwh"].mean()).to_numpy()
    return float((np.asarray(kwh, dtype=float) * g).sum() / 1e6)
