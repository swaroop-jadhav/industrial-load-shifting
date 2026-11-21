"""
Download German day-ahead electricity prices (15-minute) from the Energy-Charts API.

WHAT THIS SCRIPT DOES
1. Splits the period (see config.py) into monthly chunks.
2. Asks the API for each month's prices (the API allows only ~2 requests per minute,
   so the script waits between requests -> the full year takes about 6 minutes).
3. Combines all months, removes duplicates, checks data quality.
4. Saves one clean CSV: data/raw/day_ahead_prices_de_lu.csv

HOW TO RUN (from the project folder):
    python src/download_prices.py

Data source: Bundesnetzagentur | SMARD.de via api.energy-charts.info (Fraunhofer ISE), CC BY 4.0.
"""
from __future__ import annotations

import sys
import time

import pandas as pd
import requests

import config

API_V2 = "https://api.energy-charts.info/v2/price"
API_V1 = "https://api.energy-charts.info/price"   # fallback (older format)
SECONDS_BETWEEN_REQUESTS = 35                      # stay under 2 requests/minute
MAX_RETRIES = 4


# -----------------------------------------------------------------------------
# 1. Talking to the API
# -----------------------------------------------------------------------------
def _get_json(url: str, params: dict) -> dict:
    """GET a URL and return JSON. Waits and retries if the API says 'too many requests'."""
    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.get(url, params=params, timeout=60)
        if response.status_code == 429:                       # rate limit hit
            wait = int(response.headers.get("Retry-After", 60))
            print(f"   Rate limit reached - waiting {wait}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)
            continue
        response.raise_for_status()                           # stop on other errors
        return response.json()
    raise RuntimeError(f"Gave up after {MAX_RETRIES} attempts: {url} {params}")


def _parse_v2(payload: dict) -> pd.DataFrame:
    """
    v2 format: {"unit": ..., "series": [{"id": ...}], "data": [{"timestamp": ..., "values": {id: price}}]}
    """
    series_id = payload["series"][0]["id"]
    rows = [
        {"timestamp": entry["timestamp"], "price": entry["values"].get(series_id)}
        for entry in payload["data"]
    ]
    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp"], utc=True)
    df.attrs["unit"] = payload.get("unit", "unknown")
    return df[["timestamp_utc", "price"]]


def _parse_v1(payload: dict) -> pd.DataFrame:
    """v1 format: {"unix_seconds": [...], "price": [...], "unit": ...}"""
    df = pd.DataFrame({"unix": payload["unix_seconds"], "price": payload["price"]})
    df["timestamp_utc"] = pd.to_datetime(df["unix"], unit="s", utc=True)
    df.attrs["unit"] = payload.get("unit", "unknown")
    return df[["timestamp_utc", "price"]]


def fetch_period(start: str, end: str) -> pd.DataFrame:
    """Fetch prices between two dates. Tries the v2 API first, falls back to v1."""
    params = {"bzn": config.BIDDING_ZONE, "start": start, "end": end}
    try:
        return _parse_v2(_get_json(API_V2, params))
    except (KeyError, IndexError, requests.HTTPError) as err:
        print(f"   v2 API failed ({err!r}) - trying v1")
        return _parse_v1(_get_json(API_V1, params))


# -----------------------------------------------------------------------------
# 2. Download month by month
# -----------------------------------------------------------------------------
def download_all() -> pd.DataFrame:
    month_starts = pd.date_range(config.PRICE_START, config.PRICE_END, freq="MS")
    chunks, unit = [], None

    for i, month_start in enumerate(month_starts, start=1):
        # Ask for one extra day so no quarter-hour at the month edge is lost;
        # duplicates are removed afterwards.
        month_end = month_start + pd.offsets.MonthBegin(1)
        print(f"[{i}/{len(month_starts)}] {month_start:%Y-%m} ...", end=" ", flush=True)
        df = fetch_period(f"{month_start:%Y-%m-%d}", f"{month_end:%Y-%m-%d}")
        unit = unit or df.attrs.get("unit")
        print(f"{len(df):,} rows")
        chunks.append(df)
        if i < len(month_starts):
            time.sleep(SECONDS_BETWEEN_REQUESTS)

    prices = pd.concat(chunks, ignore_index=True)
    prices.attrs["unit"] = unit
    return prices


# -----------------------------------------------------------------------------
# 3. Clean and check (never trust a download without checking it!)
# -----------------------------------------------------------------------------
def clean_and_validate(prices: pd.DataFrame) -> pd.DataFrame:
    unit = prices.attrs.get("unit")
    prices = (
        prices.drop_duplicates("timestamp_utc")
        .sort_values("timestamp_utc")
        .reset_index(drop=True)
    )

    # Keep only the requested period (in German local time)
    local = prices["timestamp_utc"].dt.tz_convert(config.LOCAL_TZ)
    start = pd.Timestamp(config.PRICE_START, tz=config.LOCAL_TZ)
    end = pd.Timestamp(config.PRICE_END, tz=config.LOCAL_TZ) + pd.Timedelta(days=1)
    prices = prices[(local >= start) & (local < end)].copy()

    prices["timestamp_local"] = prices["timestamp_utc"].dt.tz_convert(config.LOCAL_TZ)
    prices = prices.rename(columns={"price": "price_eur_mwh"})

    # ---- Quality checks -------------------------------------------------
    print("\nDATA QUALITY REPORT")
    print(f"  Unit reported by API : {unit}")
    if unit and "MWh" not in str(unit):
        print("  WARNING: expected EUR/MWh - check the unit before analysing!")

    steps = prices["timestamp_utc"].diff().dropna().value_counts()
    print(f"  Time steps found     : {dict(steps.head(3))}")

    expected = pd.date_range(prices["timestamp_utc"].min(), prices["timestamp_utc"].max(), freq="15min")
    missing = expected.difference(prices["timestamp_utc"])
    print(f"  Rows                 : {len(prices):,} (expected {len(expected):,})")
    print(f"  Missing quarter-hours: {len(missing)}")
    print(f"  Empty prices (null)  : {prices['price_eur_mwh'].isna().sum()}")
    print(f"  Price range          : {prices['price_eur_mwh'].min():.2f} to "
          f"{prices['price_eur_mwh'].max():.2f} EUR/MWh")
    print(f"  Negative-price slots : {(prices['price_eur_mwh'] < 0).sum():,}")

    return prices[["timestamp_utc", "timestamp_local", "price_eur_mwh"]]


def main() -> None:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {config.BIDDING_ZONE} day-ahead prices "
          f"{config.PRICE_START} to {config.PRICE_END}\n")
    try:
        prices = clean_and_validate(download_all())
    except requests.ConnectionError:
        sys.exit("No connection to api.energy-charts.info - check your internet and try again.")

    prices.to_csv(config.PRICES_RAW_FILE, index=False)
    print(f"\nSaved -> {config.PRICES_RAW_FILE}")


if __name__ == "__main__":
    main()
