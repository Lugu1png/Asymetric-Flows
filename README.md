# Monetary tightening and bond-fund flow–performance asymmetry (N-PORT)

Does the flow–performance relation of US bond funds show the concavity documented by
Goldstein, Jiang & Ng (2017, JFE), and did it strengthen during the 2022 tightening?

**Status:** Days 1–3 (data pipeline). Regressions not yet run; no results reported.

## Pipeline

```bash
pip install -r requirements.txt
export SEC_USER_AGENT="Your Name your.email@uni.lu"   # SEC fair-access policy (no API key needed)
python -m nportflows.run           # all steps below; re-run any time to pick up new quarters
```

`run` skips work already done and rebuilds the panel only when new data arrived
(`--rebuild` forces it, `--skip-download` stays offline). The quarters run from 2019q4 to the
current quarter (`NPORT_LAST_Q=auto`); quarters not yet published are skipped and collected
by a later run. The steps can also be run one by one:

```bash
python -m nportflows.download      # ~28 zips, ~11 GB, checksums in data/raw/manifest.json
python -m nportflows.extract       # per-quarter tables -> data/interim/<quarter>/
python -m nportflows.build_panel   # -> data/processed/panel.parquet, filings.parquet
python -m nportflows.checks        # -> reports/data_quality.md + CSVs
python tests/test_synthetic.py     # end-to-end test on synthetic zips with known truth
```

On Windows PowerShell set the variable with `$env:SEC_USER_AGENT="Your Name your.email@uni.lu"`.
If `data/interim/` was built by an older version (no `pct_cash`/`pct_sov` in the composition
tables), delete it and re-run `extract`; `build_panel` stops with a message if so.

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
- **Returns:** class returns, equal-weighted within fund (class net assets are not in N-PORT), after dropping classes more than 0.5pp from the fund's median class return (classes share one portfolio, so only fees should separate them). Two classes that disagree by more than 1pp give a missing fund return. The all-class mean and the median are kept as alternatives.
- **Sample:** 2020-01 to the last month with complete filing coverage (`SAMPLE_END="auto"`: ≥ 95% of the prior 12-month median number of reporting funds). The newest months are incomplete because funds with later fiscal quarters have not filed yet.
- **Returns units:** detected from the median |raw return| (`RETURNS_IN_PERCENT="auto"`); the choice is logged in `reports/build_meta.json`.
- **Net assets:** reported only at month 3. Lagged NA rebuilt from NA_m = NA_{m−1}(1+r_m−d) + S_m − R_m, where d is the unreported cash-distribution leakage (cash paid minus reinvested, as a share of NA). Anchored on the previous filing's reported NA when it is 1–3 months earlier; d is solved so that path closes on this filing's reported NA (if the unadjusted closure error is ≤ 5%), else the fund's median d is used. Backward from this filing's NA, per month, wherever the anchored path is missing. Unadjusted closure error, d and the method per month are reported.
- **Flows:** (sales − redemptions) / lagged NA; version including reinvestments kept.
- **Performance:** lagged raw return, and lagged category-adjusted return (minus the leave-one-out mean of peers of the same bond type and month; peers are size-filtered, redeemable and not ETF-named). Lags merged by calendar month.
- **Bond funds:** median holdings composition on filings up to 2021-12-31 (no look-ahead into the tightening): debt + cash-like (repo, MMF shares) ≥ 70%, debt alone ≥ 50% and equity ≤ 10% of NA; gov (US) / muni / sovereign_nonus / corp if ≥ 50% of the debt book, else mixed.
- **Flags, not drops:** lagged NA ≥ $10m (and $50m), no flow activity (closed-end-like), |flow| > 50%, |return| > 20%, ETF by series name, last filing, implausible NA reconstruction (closure error > 5% or d outside [−0.5%, 1%] per month), dropped outlier classes. `eligible` combines the primary filters (including extreme flows and lagged returns, ETF names and implausible NA; switchable in `config.py`).

## Known limitations (open)

- ETFs are only identified by series name (N-PORT has no ETF flag). ETFs that are a share class of a mutual-fund series (e.g. Vanguard) are missed; matching to the N-CEN ETF flag would fix this.
- No fund inception dates: incubation bias cannot be addressed directly from N-PORT.
- Equal-weighted class returns are not asset-weighted fund returns.
