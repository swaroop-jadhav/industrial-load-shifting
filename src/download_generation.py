"""
Download Germany's electricity generation mix (15-minute) from the Energy-Charts API.
We use it to calculate how much CO2 each kWh from the grid causes at each quarter-hour (co2.py).

WHAT THIS SCRIPT DOES
1. Splits the price period (config.py) into monthly chunks.
2. Asks the API for each month's generation per source in MW: lignite, hard coal, gas, wind, solar, ...
   (about 2 requests per minute allowed -> the full year takes about 6 minutes).
3. Combines the months, removes duplicates, checks completeness.
4. Saves data/raw/generation_mix_de.csv

HOW TO RUN (from the project folder):
    python src/download_generation.py

Data source: Energy-Charts (Fraunhofer ISE), api.energy-charts.info, CC BY 4.0.
"""
from __future__ import annotations

import sys
import time

import pandas as pd
import requests

import config

API = "https://api.energy-charts.info/v2/public_power"
SECONDS_BETWEEN_REQUESTS = 35
MAX_RETRIES = 4


def get_json(params: dict) -> dict:
    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.get(API, params=params, timeout=90)
        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After", 60))
            print(f"   Rate limit reached - waiting {wait}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"Gave up after {MAX_RETRIES} attempts: {params}")


def parse(payload: dict) -> pd.DataFrame:
    """v2 envelope: data = [{"timestamp": ..., "values": {"solar": MW, "fossil_gas": MW, ...}}, ...]"""
    rows = [{"timestamp": d["timestamp"], **d["values"]} for d in payload["data"]]
    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df.pop("timestamp"), utc=True)
    df.attrs["unit"] = payload.get("unit")
    return df


def download_all() -> pd.DataFrame:
    months = pd.date_range(config.PRICE_START, config.PRICE_END, freq="MS")
    chunks, unit = [], None
    for i, start in enumerate(months, start=1):
        end = start + pd.offsets.MonthEnd(0)                 # 'end' is inclusive (whole last day)
        print(f"[{i}/{len(months)}] {start:%Y-%m} ...", end=" ", flush=True)
        df = parse(get_json({"country": "de", "start": f"{start:%Y-%m-%d}", "end": f"{end:%Y-%m-%d}"}))
        unit = unit or df.attrs.get("unit")
        print(f"{len(df):,} rows")
        chunks.append(df)
        if i < len(months):
            time.sleep(SECONDS_BETWEEN_REQUESTS)
    out = pd.concat(chunks, ignore_index=True)
    out.attrs["unit"] = unit
    return out


def clean_and_validate(gen: pd.DataFrame) -> pd.DataFrame:
    unit = gen.attrs.get("unit")
    gen = gen.drop_duplicates("timestamp_utc").sort_values("timestamp_utc").reset_index(drop=True)
    print("\nDATA QUALITY REPORT")
    print(f"  Unit reported by API : {unit}")
    expected = pd.date_range(gen["timestamp_utc"].min(), gen["timestamp_utc"].max(), freq="15min")
    print(f"  Rows                 : {len(gen):,} (expected {len(expected):,})")
    print(f"  Missing quarter-hours: {len(expected.difference(gen['timestamp_utc']))}")
    sources = [c for c in gen.columns if c not in ("timestamp_utc",)]
    print(f"  Columns              : {len(sources)} -> {', '.join(sources)}")
    empty = gen[sources].isna().mean().loc[lambda s: s > 0.01]
    if len(empty):
        print(f"  Columns with >1% empty values: {empty.round(3).to_dict()}")
    if "solar" in gen and "load" in gen:
        print(f"  Average load {gen['load'].mean():,.0f} MW | average solar {gen['solar'].mean():,.0f} MW")
    return gen


def main() -> None:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading German generation mix {config.PRICE_START} to {config.PRICE_END}\n")
    try:
        gen = clean_and_validate(download_all())
    except requests.ConnectionError:
        sys.exit("No connection to api.energy-charts.info - check your internet and try again.")
    gen.to_csv(config.GENERATION_FILE, index=False)
    print(f"\nSaved -> {config.GENERATION_FILE}")


if __name__ == "__main__":
    main()
