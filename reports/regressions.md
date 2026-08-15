# Flow-performance regressions

Dependent variable: monthly net flow (share of lagged NA). Performance: lagged category-adjusted monthly return unless stated. Controls: lagged flow, log lagged NA. Tightening = 2022-03 to 2023-07. SE clustered by fund in parentheses; * p<0.1, ** p<0.05, *** p<0.01. Flows and performance winsorised at 1%/99%.

| spec | slope_above (b1) | slope_below (b1+b2) | concavity (b2) | tight: slope_above | tight: slope_below | change in concavity (b4) | N | funds |
|---|---|---|---|---|---|---|---|---|
| 1 base, month FE | -0.005 (0.026) | 0.084*** (0.024) | 0.089** (0.041) |  |  |  | 153,230 | 2,561 |
| 2 base, fund+month FE | 0.060** (0.024) | 0.023 (0.023) | -0.037 (0.039) |  |  |  | 153,230 | 2,561 |
| 3 tightening, fund+month FE (main) | 0.020 (0.028) | 0.076*** (0.027) | 0.056 (0.045) | 0.138*** (0.038) | -0.078** (0.035) | -0.272*** (0.070) | 153,230 | 2,561 |
| 4 = 3 with raw return | 0.012 (0.020) | 0.110*** (0.023) | 0.098*** (0.033) | 0.174*** (0.036) | -0.039 (0.028) | -0.311*** (0.057) | 153,230 | 2,561 |
| 5 = 3, funds >= $50m | 0.021 (0.029) | 0.082*** (0.027) | 0.061 (0.046) | 0.125*** (0.040) | -0.090** (0.037) | -0.276*** (0.072) | 139,641 | 2,323 |
| 6 = 3, no fund FE | -0.040 (0.029) | 0.136*** (0.027) | 0.177*** (0.046) | 0.079** (0.040) | -0.028 (0.036) | -0.283*** (0.068) | 153,230 | 2,561 |
| 7 = 3, corp only | 0.038 (0.042) | 0.024 (0.046) | -0.015 (0.076) | 0.016 (0.056) | -0.000 (0.052) | -0.002 (0.115) | 65,014 | 1,115 |
| 7 = 3, gov only | 0.010 (0.064) | 0.008 (0.053) | -0.002 (0.096) | 0.300*** (0.087) | -0.211*** (0.077) | -0.509*** (0.132) | 33,110 | 563 |
| 7 = 3, muni only | 0.171*** (0.058) | 0.121** (0.050) | -0.049 (0.092) | 0.171* (0.092) | -0.062 (0.094) | -0.184 (0.174) | 39,447 | 618 |

Reading: a slope of 0.5 means a 1pp higher return last month goes with 0.5pp more net flow this month. Concavity b2 > 0: flows react more to underperformance than to outperformance. b4 > 0: stronger during tightening.
