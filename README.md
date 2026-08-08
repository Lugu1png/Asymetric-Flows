# Monetary tightening and bond-fund flow–performance asymmetry (N-PORT)

Does the flow–performance relation of US bond funds show the concavity documented by
Goldstein, Jiang & Ng (2017, JFE), and did it strengthen during the 2022 tightening?

**Status:** Days 1–3 (data pipeline). Regressions not yet run; no results reported.

## Pipeline

```bash
pip install -r requirements.txt
export SEC_USER_AGENT="Your Name your.email@uni.lu"   # SEC fair-access policy
python -m nportflows.download      # ~27 zips, ~11 GB, checksums in data/raw/manifest.json
python -m nportflows.extract       # per-quarter tables -> data/interim/<quarter>/
python -m nportflows.build_panel   # -> data/processed/panel.parquet, filings.parquet
python -m nportflows.checks        # -> reports/data_quality.md + CSVs
python tests/test_synthetic.py     # end-to-end test on synthetic zips with known truth
```

All analytical choices (thresholds, cut-off dates, code lists) are in `nportflows/config.py`.

## Data source

SEC DERA *Form N-PORT Data Sets* (quarterly zips by **filing** quarter, 2019q4 onward),
field definitions in the [N-PORT readme](https://www.sec.gov/files/nport_readme.pdf).

| Table | Fields used |
|---|---|
| SUBMISSION | ACCESSION_NUMBER, FILING_DATE, SUB_TYPE, REPORT_DATE, IS_LAST_FILING |
| REGISTRANT | CIK, REGISTRANT_NAME |
| FUND_REPORTED_INFO | SERIES_ID, SERIES_NAME, NET_ASSETS, SALES_FLOW_MON1–3, REINVESTMENT_FLOW_MON1–3, REDEMPTION_FLOW_MON1–3 |
| MONTHLY_TOTAL_RETURN | CLASS_ID, MONTHLY_TOTAL_RETURN1–3 |
| FUND_REPORTED_HOLDING | PERCENTAGE, PAYOFF_PROFILE, ASSET_CAT, ISSUER_TYPE, DERIVATIVE_CAT |

## Construction

- **Unit of observation:** series (fund) × calendar month. Month *k* of a filing = report month − (3 − *k*); fiscal quarters differ across funds.
- **Amendments:** latest filing per (series, report month), across all zips; then latest per (series, month).
- **Returns:** class returns, equal-weighted within fund (class net assets are not in N-PORT). Median across classes kept as an alternative.
- **Net assets:** reported only at month 3. Lagged NA rebuilt from NA_m = NA_{m−1}(1+r_m) + S_m − R_m (assumes cash distributions ≈ reinvested distributions); forward from the previous filing's reported NA when available, backward otherwise. Closure error vs reported NA is reported.
- **Flows:** (sales − redemptions) / lagged NA; version including reinvestments kept.
- **Performance:** lagged raw return, and lagged category-adjusted return (minus leave-one-out mean of same bond type and month). Lags merged by calendar month.
- **Bond funds:** median holdings composition on filings up to 2021-12-31 (no look-ahead into the tightening): debt ≥ 70% and equity ≤ 10% of NA; gov / muni / corp if ≥ 50% of the debt book, else mixed.
- **Flags, not drops:** lagged NA ≥ $10m (and $50m), no flow activity (closed-end-like), |flow| > 50%, last filing. `eligible` combines the primary filters.

## Known limitations (open)

- ETFs and open-end mutual funds are not yet separated (N-PORT has no ETF flag); ETF flows are AP creations/redemptions and should be analysed separately or excluded.
- No fund inception dates: incubation bias cannot be addressed directly from N-PORT.
- Equal-weighted class returns are not asset-weighted fund returns.
