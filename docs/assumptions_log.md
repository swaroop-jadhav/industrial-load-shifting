# Assumptions & Decision Log

Senior analysts write down every assumption and decision *when they make it*.
In interviews and in your final report, this is what shows you think like a professional.
Add a row every time you decide something.

## Assumptions

| # | Assumption | Why | Impact if wrong | Date |
|---|---|---|---|---|
| A1 | The plant buys electricity at the day-ahead spot price (dynamic contract). | Load shifting only saves money with a spot-linked contract. | With a fixed-price contract, savings ≈ 0 → we also report the savings a company *could* unlock by switching. | Week 1 |
| A2 | Grid fees, taxes and levies are the same at all times of day. | Simplification; they are mostly fixed per kWh. | Savings are calculated on the wholesale part only — stated clearly in results. | Week 1 |
| A3 | The 2017 HIPE load pattern is representative of a typical week today. | Production processes change slowly; we need the *shape*, not the date. | Absolute € numbers may differ; the method stays valid. | Week 1 |
| A4 | Flexible candidates: SolderingOven and VacuumPump1 (about 60% of active machine energy, running only 12% and 20% of the week); HighTemperatureOven as a secondary candidate (highest power, 3.6 kW, but rarely used). Jobs are shifted only within the weekday day shift. | All machines run only on weekdays during the day shift and work in batches; no access to the plant's production planners. | Some batches may be tied to the process order (e.g. oven and vacuum pump running together); to be checked in Week 2. | Week 1 |

## Decisions

| # | Decision | Alternatives considered | Reason | Date |
|---|---|---|---|---|
| D1 | Use 12 months of prices from 1 Oct 2025 – 30 Sep 2026. | Longer history incl. hourly prices. | Only the 15-minute market is relevant for today's decisions; 12 months covers all seasons. | Week 1 |
| D2 | Resample machine data from ~5 s to 15 min (mean kW). | Keep 5 s data. | Must match price resolution; 15-min mean power × 0.25 h = energy in kWh. | Week 1 |
| D3 | Energy-Charts API instead of manual SMARD download. | SMARD CSV export. | Reproducible: anyone can re-run the script. Same underlying data. | Week 1 |
| D4 | Keep extreme prices (min −499.99 €/MWh on 1 May 2026 13:15–14:15; max 747.10 €/MWh on 24 Jun 2026 20:45, 700+ €/MWh on 14 Sep 2026 19:15–20:00). | Remove or cap outliers. | Validated as real market events: price floor at midday on a public holiday (solar surplus, low demand), several consecutive slots; maxima in the evening when solar drops. Extremes are where load shifting saves money, so removing them would understate savings. Use median alongside mean. | Week 1 |
| D5 | Treat small negative power values (≥ −0.03 kW) as sensor noise and set them to 0. | Keep as-is; treat as energy feed-back. | They occur only when machines are off and are tiny; none of these machines can generate electricity. | Week 1 |
| D6 | Exclude ChipPress, WashingMachine and VacuumOven from the flexibility analysis for this week. | Keep all 10 machines. | Average ≈ 0.00 kW, so they were idle or in standby during 23–29 Oct 2017. | Week 1 |
| D7 | Use HIPE to build and test the method; add KIT's SPARK dataset (22 heavier machines plus PV) for the main business case. | Rely on HIPE only. | The 10 metered HIPE machines use only ~102 kWh/week, about 4% of the plant's 2,714 kWh/week, so the business case would be only a few hundred € per year. | Week 1 |
