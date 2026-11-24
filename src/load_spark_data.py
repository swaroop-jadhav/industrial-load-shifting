"""
Turn the SPARK machine files (5-second active power, one file per machine and year) into one
clean 15-minute table - the same format as the HIPE table from Week 1.

EXPECTED FILES (one folder per machine, as in the original dataset):
    data/raw/spark/TEC_Chiron800/2024_P_total.csv.xz
    data/raw/spark/TEC_DMU125MB/2024_P_total.csv.xz
    ...
    (a deeper layout like TEC_Chiron800/P_total/2024_P_total.csv.xz also works)

WHAT THIS SCRIPT DOES
1. Finds every *P_total*.csv.xz file and reads the machine name from its folder.
2. Reads the file (pandas unpacks .xz by itself), converts W -> kW.
3. Converts the German local timestamps (CET/CEST) to UTC, handling the clock changes.
4. Averages to 15 minutes and calculates energy (kWh = kW x 0.25 h).
5. Checks data coverage: 15 minutes should contain 180 readings (every 5 s).
6. Saves data/processed/spark_load_15min.csv
   columns: timestamp_utc | machine | avg_kw | energy_kwh | coverage

HOW TO RUN:
    python src/load_spark_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

import config

TIME_COL = "WsDateTime"
READINGS_PER_QUARTER_HOUR = 15 * 60 // 5      # 180
MIN_COVERAGE = 0.5                            # < 50 % of readings -> treat quarter-hour as missing


def machine_name_from_path(path: Path) -> str:
    """Use the first folder name that looks like a SPARK machine (TEC_... / EPI_...)."""
    for part in reversed(path.parts[:-1]):
        if part.startswith(("TEC_", "EPI_")):
            return part
    sys.exit(f"Cannot tell which machine this file belongs to: {path}\n"
             "Put each file in a folder named after its machine, e.g. data/raw/spark/TEC_Chiron800/")


def to_utc(raw_times: pd.Series) -> tuple[pd.Series, str]:
    """
    SPARK timestamps are German local time. Two special cases once a year:
      - spring: 02:00-03:00 does not exist  -> dropped
      - autumn: 02:00-03:00 happens twice   -> 'infer' uses the order to tell them apart
    """
    first = str(raw_times.iloc[0])
    if first.endswith("Z") or "+" in first[10:] or first[19:].count("-"):
        return pd.to_datetime(raw_times, utc=True, format="ISO8601"), "timestamps had a UTC offset"

    local = pd.to_datetime(raw_times, format="ISO8601")
    try:
        aware = local.dt.tz_localize(config.LOCAL_TZ, ambiguous="infer", nonexistent="NaT")
        how = "local time, clock changes inferred"
    except Exception:                                   # e.g. a data gap during the autumn hour
        aware = local.dt.tz_localize(config.LOCAL_TZ, ambiguous="NaT", nonexistent="NaT")
        how = "local time, ambiguous autumn hour dropped"
    return aware.dt.tz_convert("UTC"), how


def load_one_machine(path: Path) -> pd.DataFrame:
    machine = machine_name_from_path(path)
    print(f"  {machine:<15}", end=" ", flush=True)

    raw = pd.read_csv(path)                              # .xz is unpacked automatically
    value_cols = [c for c in raw.columns if c != TIME_COL]
    power_col = next((c for c in value_cols if "P_total" in c), value_cols[0])

    times, how = to_utc(raw[TIME_COL])
    kw = pd.to_numeric(raw[power_col], errors="coerce") / 1000          # W -> kW
    negatives = int((kw < 0).sum())
    kw = kw.clip(lower=0)                                               # same rule as D5

    series = pd.Series(kw.to_numpy(), index=pd.DatetimeIndex(times)).loc[lambda s: s.index.notna()]
    agg = series.resample(config.RESAMPLE_RULE).agg(["mean", "count"])

    out = pd.DataFrame({
        "avg_kw": agg["mean"].where(agg["count"] >= MIN_COVERAGE * READINGS_PER_QUARTER_HOUR),
        "coverage": (agg["count"] / READINGS_PER_QUARTER_HOUR).clip(upper=1).round(3),
    })
    out["energy_kwh"] = out["avg_kw"] * 0.25
    out["machine"] = machine
    print(f"{len(raw):>10,} readings | {out['coverage'].mean():5.1%} coverage | "
          f"avg {out['avg_kw'].mean():6.2f} kW | {negatives:,} negative set to 0 | {how}")
    return out.rename_axis("timestamp_utc").reset_index()


def quality_report(df: pd.DataFrame) -> None:
    print("\nDATA QUALITY REPORT")
    summary = df.groupby("machine").agg(
        quarter_hours=("avg_kw", "size"),
        missing_quarter_hours=("avg_kw", lambda s: s.isna().sum()),
        coverage_pct=("coverage", lambda s: 100 * s.mean()),
        avg_kw=("avg_kw", "mean"),
        max_kw=("avg_kw", "max"),
        energy_mwh=("energy_kwh", lambda s: s.sum() / 1000),
    ).round(2).sort_values("energy_mwh", ascending=False)
    print(summary.to_string())
    print(f"\nTotal energy: {summary['energy_mwh'].sum():,.1f} MWh")
    low = summary.index[summary["coverage_pct"] < 90].tolist()
    if low:
        print(f"NOTE: coverage below 90% for {low} - check the gaps before trusting their totals.")
    found = set(summary.index)
    missing = [m for m in config.SPARK_MACHINES if m not in found]
    if missing:
        print(f"NOTE: no file found for {missing}")
    print(f"Period: {df['timestamp_utc'].min()} to {df['timestamp_utc'].max()}")


def main() -> None:
    files = sorted(p for p in config.SPARK_DIR.rglob("*P_total*.csv.xz") if "_EMPTY" not in p.name)
    if not files:
        sys.exit(f"No *P_total*.csv.xz files found in {config.SPARK_DIR}")

    print(f"Found {len(files)} machine files in {config.SPARK_DIR}\n")
    machines = pd.concat([load_one_machine(f) for f in files], ignore_index=True)
    machines = machines[["timestamp_utc", "machine", "avg_kw", "energy_kwh", "coverage"]]

    quality_report(machines)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    machines.to_csv(config.SPARK_LOAD_FILE, index=False)
    print(f"\nSaved -> {config.SPARK_LOAD_FILE}")


if __name__ == "__main__":
    main()
