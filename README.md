# Industrial Load Shifting: Cutting a Factory's Electricity Costs with 15-Minute Prices

> **Status:** 🚧 In progress — Week 3 of 6 (price forecast)

## Business problem

German manufacturers pay some of the highest electricity prices in Europe, and the
wholesale price changes every 15 minutes (since 1 October 2025). Some machines —
pumps, compressors, chip presses — do not have to run at a fixed time.

**Question:** *How much could a German production site save per year if it moved its
flexible machine loads to the cheapest 15-minute periods, without disrupting production?*

**Stakeholder:** Plant / energy manager of a small-to-mid-sized German manufacturer.

**Decision supported:** Which machines to reschedule, when to run them, and whether the
savings justify switching to a dynamic (spot-linked) electricity contract.

## Data

| Source | What | Resolution | Licence |
|---|---|---|---|
| [Energy-Charts API](https://api.energy-charts.info/) (Fraunhofer ISE), data from Bundesnetzagentur / SMARD.de | Day-ahead electricity prices, bidding zone DE-LU | 15 min | CC BY 4.0 |
| [HIPE](https://www.energystatusdata.kit.edu/hipe.php) (KIT Karlsruhe) | Machine-level power of 10 machines + main terminal of a real electronics production plant | ~5 s → resampled to 15 min | CC BY 4.0 |
| [SPARK](https://doi.org/10.35097/bjdg3m3rg5jv3skk) (KIT Karlsruhe, 2026) — **main dataset** | 11 TEC workshop machines (mills, lathes, wire EDM, chillers), 2024 | 5 s → 15 min | CC BY 4.0 |

## Approach

1. **Explore** machine load profiles and 15-minute price patterns *(Week 1)*
2. **Cost baseline:** what does the current schedule cost at 15-minute prices? *(Week 2)*
3. **Price forecast** 2–7 days ahead for production planning *(Week 3)*
4. **Optimise** flexible loads under production constraints (linear programming) *(Week 4)*
5. **Business case:** annual € and CO₂ savings, dashboard, management summary *(Weeks 5–6)*

## Key assumptions

See [`docs/assumptions_log.md`](docs/assumptions_log.md). The most important one: the HIPE
load data is from 2017, so its **typical weekly load pattern** is replayed against
**current (2025/26) prices**. This is a standard "what-if" approach.

## Project structure

```
├── data/
│   ├── raw/            # original downloads — never edited (not in Git)
│   └── processed/      # cleaned, analysis-ready files (not in Git)
├── docs/               # guides, assumptions and decision log
├── notebooks/          # analysis notebooks, numbered in order
├── reports/figures/    # exported charts for README / slides
└── src/                # reusable Python scripts
```

## How to run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt

python src/download_prices.py        # ~6 minutes (API rate limit)
python src/load_machine_data.py      # after downloading HIPE into data/raw/hipe/
python src/load_spark_data.py        # after downloading SPARK files into data/raw/spark/<machine>/
jupyter lab                          # notebooks 01_data_exploration, 02_cost_baseline, 03_price_forecast
```

## Results

*Coming in Week 5.*

---
*Data attribution: Bundesnetzagentur | SMARD.de via energy-charts.info (Fraunhofer ISE), CC BY 4.0.
HIPE: Bischof et al., KIT, CC BY 4.0. SPARK: Sievers, Bischof, Simon, Blank, KIT (2026), CC BY 4.0.*
