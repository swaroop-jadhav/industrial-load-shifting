"""
Take ONLY the active-power file (P_total, 2024) out of each downloaded SPARK machine ZIP.

Each machine ZIP from RADAR4KIT contains ~125 measurements (voltages, currents, harmonics ...).
We only need one: the total active power. Unpacking everything would cost many GB of disk space,
so this script copies just that one file into data/raw/spark/<machine>/.

Usage:
    python src/extract_spark_power.py                      # looks in your Downloads folder
    python src/extract_spark_power.py "D:\\some\\folder"    # or in another folder
Afterwards you can delete the ZIP files.
"""
from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path

import config

# e.g. TEC_Chiron800/P_total/2024_P_total.csv.xz  (but NOT P_total_f, the fundamental-only variant)
WANTED = re.compile(rf"(^|/){config.SPARK_YEAR}_P_total\.csv\.xz$")


def extract(zip_path: Path) -> None:
    machine = zip_path.stem
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist() if WANTED.search(m)]
        if not members:
            hints = [m for m in zf.namelist() if "P_total" in m][:10]
            print(f"  {machine:<15} NOT FOUND - files with 'P_total' in this ZIP: {hints}")
            return
        target_dir = config.SPARK_DIR / machine
        target_dir.mkdir(parents=True, exist_ok=True)
        for member in members:
            target = target_dir / Path(member).name
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            print(f"  {machine:<15} -> {target.relative_to(config.PROJECT_ROOT)} "
                  f"({target.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads"
    zips = sorted(p for p in folder.glob("*.zip") if p.stem in config.SPARK_MACHINES)
    if not zips:
        sys.exit(f"No TEC_*.zip machine files found in {folder}")

    print(f"Found {len(zips)} of {len(config.SPARK_MACHINES)} machine ZIPs in {folder}\n")
    for z in zips:
        try:
            extract(z)
        except zipfile.BadZipFile:
            print(f"  {z.stem:<15} DAMAGED or incomplete download - download it again")
    missing = [m for m in config.SPARK_MACHINES if m not in {z.stem for z in zips}]
    if missing:
        print(f"\nStill missing: {missing}")
    print("\nNext: python src/load_spark_data.py")


if __name__ == "__main__":
    main()
