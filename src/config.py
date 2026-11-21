"""
Central settings for the project.

Senior-analyst habit: keep every "magic number" (dates, paths, zone codes) in ONE place.
If you want to change the analysis period, you change it here, not in five scripts.
"""
from pathlib import Path

# --- Paths -------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
HIPE_DIR = RAW_DIR / "hipe"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
FIGURES_DIR = PROJECT_ROOT / "reports" / "figures"

PRICES_RAW_FILE = RAW_DIR / "day_ahead_prices_de_lu.csv"
MACHINE_LOAD_FILE = PROCESSED_DIR / "machine_load_15min.csv"

# --- Electricity prices ------------------------------------------------------
BIDDING_ZONE = "DE-LU"          # Germany-Luxembourg market area
# The day-ahead market switched to 15-minute products on 1 Oct 2025.
# We analyse 12 full months of the new 15-minute market.
PRICE_START = "2025-10-01"
PRICE_END = "2026-09-30"        # inclusive
LOCAL_TZ = "Europe/Berlin"

# --- Machine data ------------------------------------------------------------
RESAMPLE_RULE = "15min"         # match the price resolution
