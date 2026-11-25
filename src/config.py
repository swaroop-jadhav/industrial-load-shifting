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
GENERATION_FILE = RAW_DIR / "generation_mix_de.csv"          # Week 5: for CO2 intensity
DASHBOARD_DATA_DIR = PROJECT_ROOT / "dashboard" / "data"        # small result tables for Streamlit / Power BI
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

# --- SPARK (KIT, 2026): the main dataset from Week 2 on (decision D7) ------------
SPARK_DIR = RAW_DIR / "spark"
SPARK_LOAD_FILE = PROCESSED_DIR / "spark_load_15min.csv"
SPARK_YEAR = 2024
# The 11 machines of the TEC workshop (only recorded in 2024, see Sievers et al. 2026)
SPARK_MACHINES = {
    "TEC_48S":       "48S (lathe)",
    "TEC_CFST161":   "CF ST 161 (water chiller)",
    "TEC_Chiron800": "Chiron 800 (5-axis mill)",
    "TEC_CTX800TC":  "CTX 800 TC (lathe-mill)",
    "TEC_DMF3008":   "DMF 300/8 (5-axis mill)",
    "TEC_DMU125MB":  "DMU 125 (5-axis mill)",
    "TEC_DNG50evo":  "DNG 50 evo (mill)",
    "TEC_E30D2":     "E30 D2 (lathe)",
    "TEC_E110":      "E110 (lathe)",
    "TEC_JWA24":     "JWA 24 (liquid cooler)",
    "TEC_MV2400R":   "MV 2400 R (wire EDM)",
}

# --- Load shifting rules (used for the upper bound in Week 2, optimisation in Week 4)
SHIFT_WINDOW_HOURS = (6, 22)    # jobs may be placed between 06:00 and 22:00 (two shifts)
