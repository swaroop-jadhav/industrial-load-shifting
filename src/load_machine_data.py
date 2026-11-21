"""
Turn the raw HIPE machine files (~5-second readings) into one clean 15-minute table.

WHAT THIS SCRIPT DOES
1. Finds every machine CSV in data/raw/hipe/
2. Reads ONLY the two columns we need (timestamp + total active power) - the files have
   100-360 columns and are huge, so reading everything would crash a laptop.
3. Converts power to kW and averages it per 15 minutes (same resolution as prices).
4. Calculates energy: kWh = average kW x 0.25 hours.
5. Saves one long table: data/processed/machine_load_15min.csv
   columns: timestamp_utc | machine | avg_kw | energy_kwh | sample_count

HOW TO RUN (after unzipping HIPE into data/raw/hipe/):
    python src/load_machine_data.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

import config

TIMESTAMP_COL = "SensorDateTime"
# Total active power is called "P_<unit>" in HIPE (pattern <Quantity>_<Unit>), e.g. P_kW
POWER_COL_PATTERN = re.compile(r"^P_(kW|W)$")
CHUNK_ROWS = 500_000            # read big files piece by piece to save memory


def machine_name_from_file(path: Path) -> str:
    """'ChipPress_PhaseCount_3_geq_2017-10-23_lt_2017-10-30.csv' -> 'ChipPress'"""
    return re.split(r"_PhaseCount|_geq_", path.stem)[0]


def find_power_column(path: Path) -> tuple[str, float]:
    """Look at the header only and return (power column name, factor to convert to kW)."""
    header = pd.read_csv(path, nrows=0).columns
    for col in header:
        match = POWER_COL_PATTERN.match(col)
        if match:
            return col, (1.0 if match.group(1) == "kW" else 0.001)
    raise ValueError(
        f"No total active power column (P_kW / P_W) found in {path.name}.\n"
        f"Columns starting with 'P': {[c for c in header if c.startswith('P')][:15]}"
    )


def load_one_machine(path: Path) -> pd.DataFrame:
    machine = machine_name_from_file(path)
    power_col, to_kw = find_power_column(path)
    print(f"  {machine:<28} column '{power_col}'", end=" ... ", flush=True)

    parts, negatives = [], 0
    for chunk in pd.read_csv(path, usecols=[TIMESTAMP_COL, power_col], chunksize=CHUNK_ROWS):
        chunk["timestamp_utc"] = pd.to_datetime(chunk[TIMESTAMP_COL], utc=True, format="ISO8601")
        kw = pd.to_numeric(chunk[power_col], errors="coerce") * to_kw
        # Decision D5: small negative readings are sensor noise around zero -> set to 0
        negatives += int((kw < 0).sum())
        chunk["kw"] = kw.clip(lower=0)
        # Partial 15-min aggregates: sum + count, so chunk borders don't distort the average
        agg = (chunk.set_index("timestamp_utc")["kw"]
               .resample(config.RESAMPLE_RULE).agg(["sum", "count"]))
        parts.append(agg)

    combined = pd.concat(parts).groupby(level=0).sum()
    out = pd.DataFrame({
        "avg_kw": combined["sum"] / combined["count"].where(combined["count"] > 0),
        "sample_count": combined["count"].astype(int),
    })
    out["energy_kwh"] = out["avg_kw"] * 0.25          # 15 min = 0.25 h
    out["machine"] = machine
    out.attrs["negatives"] = negatives
    print(f"{len(out):,} quarter-hours, avg {out['avg_kw'].mean():.2f} kW, "
          f"{negatives:,} negative readings set to 0")
    return out.reset_index()


def quality_report(df: pd.DataFrame) -> None:
    print("\nDATA QUALITY REPORT")
    summary = df.groupby("machine").agg(
        quarter_hours=("avg_kw", "size"),
        empty_quarter_hours=("avg_kw", lambda s: s.isna().sum()),
        avg_kw=("avg_kw", "mean"),
        max_kw=("avg_kw", "max"),
        min_kw=("avg_kw", "min"),
        total_kwh=("energy_kwh", "sum"),
    ).round(2)
    print(summary.to_string())
    idle = summary.index[summary["total_kwh"] < 1].tolist()
    if idle:
        print(f"\nNOTE: idle this period (< 1 kWh): {idle} -> excluded from flexibility analysis (D6)")
    print(f"\nPeriod: {df['timestamp_utc'].min()} to {df['timestamp_utc'].max()}")


def main() -> None:
    files = sorted(config.HIPE_DIR.rglob("*.csv"))
    if not files:
        sys.exit(f"No CSV files found in {config.HIPE_DIR}\n"
                 "Download HIPE (one-week version) and unzip it there - see docs/WEEK1_GUIDE.md")

    print(f"Found {len(files)} machine files in {config.HIPE_DIR}\n")
    machines = pd.concat([load_one_machine(f) for f in files], ignore_index=True)
    machines = machines[["timestamp_utc", "machine", "avg_kw", "energy_kwh", "sample_count"]]

    quality_report(machines)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    machines.to_csv(config.MACHINE_LOAD_FILE, index=False)
    print(f"\nSaved -> {config.MACHINE_LOAD_FILE}")


if __name__ == "__main__":
    main()
