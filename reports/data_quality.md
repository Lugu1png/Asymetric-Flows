# N-PORT panel: data-quality report


## Pipeline stages

- submissions (all types): 355,115
- submissions NPORT-P or NPORT-P/A: 355,115
-   unparseable REPORT_DATE: 0
-   unparseable FILING_DATE (treated as oldest): 0
- filings with SERIES_ID and REPORT_DATE: 336,295
-   filings reporting redemptions as negatives (made positive): 67,781
-   superseded by a later filing (amendments): 5,193
- filings after de-duplication: 331,102
- filings with no class returns: 0
- filings with NA bridged to the previous filing: 298,846
- filings with |closure error| > 5% (not bridged): 9,574
- filings with implausible NA reconstruction (flag_bad_na): 20,051
- series-months covered by >1 filing (kept one): 710
- months dropped at the end (incomplete filing coverage): 2
- panel series-months (all funds): 992,596
- series flagged as ETF by name: 5,973
- panel series-months eligible (bond, size, lagged ret): 153,230
- bond funds eligible in >= 1 month: 2,561
- rows with malformed ACCESSION_NUMBER (parse corruption): 0 — PASS
- raw lines rejected by the TSV parser (lost rows): 0 — PASS
- expected columns missing from a quarter's file: none — PASS

## Keys and coverage

- (SERIES_ID, month) unique: True — PASS
- max month-on-month change in #series: 2.8% (phase-in of smaller fund groups or missing filings show up here; inspect coverage_by_month.csv) — PASS
- bond-type counts (series): {'not_bond': 14023, 'corp': 1637, 'gov': 1174, 'muni': 807, 'sovereign_nonus': 176, 'mixed': 146, 'unclassified': 14}
- classification source (series): {'median_pre_cutoff': 13167, 'first_filing_post_cutoff': 4796, None: 14}
- series flagged as ETF by name (excluded from eligible): 5973

## Returns (units, class aggregation)

- return units used: percent (auto; median |raw value| = 2.28)
- sample: 2020-01 to 2026-05 (SAMPLE_END=auto)
- median |monthly return|, bond funds: 0.0086  (expect ~0.002-0.01 in decimals; ~100x larger means RETURNS_IN_PERCENT is wrong) — PASS
- share bond fund-months with |return| > 20% (lagged ones not eligible): 0.1344% — PASS
- class return spread (max-min) within fund: p1=0, p5=0, p25=0, p50=0.000191, p75=0.001, p95=0.0022, p99=0.03787
- share with raw class spread > 1pp (misreported class?): 2.589%
- fund-months where outlier classes (> 0.5% from class median) were dropped: 4.631% of multi-class fund-months
- fund-months with return set to missing (classes disagree, no majority): 1.311% — **WARN**
- |fund return change| from dropping outlier classes, where it changed: p1=0.0001673, p5=0.0005733, p25=0.003984, p50=0.007445, p75=0.009335, p95=0.01273, p99=0.01534
- share bond fund-months with missing return: 1.751%

## Net assets: accounting closure (anchored reconstruction vs reported NA)

- filings with closure check: 69,425 of 74,447 bond filings (rest have no filing 1-3 months earlier -> backward method)
- |closure error| before distribution adjustment: p1=1.533e-05, p5=7.558e-05, p25=0.0004265, p50=0.001262, p75=0.005478, p95=0.01761, p99=0.08964
- share with |closure error| < 1%: 85.6% — **WARN**
- share with |closure error| > 5% (not bridged; mergers? errors?): 1.6% — PASS
- implied monthly cash-distribution leakage d (bridged filings): p1=-0.004841, p5=-0.0005427, p25=-2.877e-05, p50=0.0002688, p75=0.001491, p95=0.004992, p99=0.008168  (bond funds: expect roughly 0 to 0.004; large |d| means flows or returns do not add up)
- source of d (bond filings): {'bridged': 68320, 'series_median': 5342, 'none': 785}
- bond filings with flag_bad_na (not bridged, or d outside [-0.005, 0.01]): 3.1% (excluded from eligible) — PASS
- NA method (bond fund-months): {'bridged': 196735, 'anchored': 4466, 'backward': 3596, 'none': 2725}
- non-positive / missing lagged NA (bond): 1.542%

## Flows

- flow, eligible obs: p1=-0.1457, p5=-0.05292, p25=-0.01253, p50=-0.001782, p75=0.009423, p95=0.0576, p99=0.1677
- flow incl. reinvestment, eligible obs: p1=-0.1425, p5=-0.05043, p25=-0.01054, p50=5.479e-05, p75=0.01233, p95=0.06169, p99=0.1721
- share eligible with |flow| > 50%: 0.000% (mergers, launches, liquidations, reporting errors: inspect before winsorising) — PASS
- share with negative sales or redemptions (redemptions already made positive): 0.0542% — PASS
- series flagged no flow activity (closed-end-like): 102
- eligible obs in a last-filing month: 517

## Timing

- share bond in-sample obs with lagged return available: 97.6%
- lagged return = own return of calendar month t-1 (by construction: merge on month+1): yes

## Holdings composition

- sum of PERCENTAGE per filing: p1=36.24, p5=93.85, p25=99.48, p50=100, p75=100.9, p95=111.2, p99=133.4
- share filings with holdings summing outside 90-110% of NA: 9.3% (leverage, shorts and derivatives make some of this legitimate) — PASS
- share of holdings with ASSET_CAT outside debt/cash/equity/derivative lists: 0.3%; top: OTHER (421,244), RE (50,924),  (31,654), COMM (1,298) — confirm none of these is a debt category missing from DEBT_CATS

## External validation (do this by hand)

- aggregate bond-fund net flows by month ($bn): reports/aggregate_net_flows_bn.csv — compare with ICI monthly bond-fund flows; 2022 should show large, persistent outflows
