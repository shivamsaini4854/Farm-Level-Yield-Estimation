# Farm Yield evaluation

Run `20261021T223804Z`. [Measured 2026-10-22: `python -X utf8 -m farm_yield.ml.train --promote`, exit 0; exact artifact parity passed.]

This is completed-season district research. It does not establish accuracy for an individual field or a recent growing season.

Train: harvest 2016–2017 (8,688 rows). Validation: 2018 (4,583). Retrospective backtest: 2019 (4,624). Years inspected in previous experiments are not a pristine unseen test. Candidates use identical eligible rows and monthly information; imputation, scaling and crop target medians are fitted only on training rows.

Selection score is the mean across crops of MAE divided by that crop’s training median yield. Lower is better; it is not MAPE.

| Model | Validation score | 2019 backtest score |
| --- | ---: | ---: |
| CropSeasonMedian | 0.4427 | 0.4945 |
| Ridge | 0.4716 | 0.5205 |
| RandomForest | 0.3664 | 0.4475 |
| GradientBoosting | 0.3874 | 0.4600 |
| XGBoost | 0.3784 | 0.4570 |
| LSTM | 0.3467 | 0.4269 |

LSTM had the lowest offline error (one 32-unit layer, seed 42, validation early stopping, 19 epochs). Random Forest is the best tabular model and is deployed to keep PyTorch out of the web service. The forest uses 120 trees, depth ≤14, minimum leaf size 3, seed 42 and one worker for exact prediction accumulation.

## Serving model, per crop

Errors are tonnes/hectare. Each row is a district/crop/season label; districts can recur across crops.

| Crop | 2019 count | MAE | RMSE | R² |
| --- | ---: | ---: | ---: | ---: |
| Rice | 320 | 0.684 | 0.882 | 0.167 |
| Maize | 375 | 1.095 | 1.418 | 0.517 |
| Moong(Green Gram) | 342 | 0.230 | 0.284 | 0.037 |
| Urad | 341 | 0.248 | 0.305 | -0.084 |
| Groundnut | 299 | 0.576 | 0.711 | 0.214 |
| Wheat | 381 | 0.693 | 0.917 | 0.460 |
| Rapeseed &Mustard | 358 | 0.368 | 0.464 | 0.249 |
| Sugarcane | 255 | 17.242 | 21.049 | 0.373 |
| Arhar/Tur | 385 | 0.382 | 1.173 | 0.033 |
| Potato | 165 | 7.070 | 9.176 | 0.165 |
| Onion | 184 | 6.800 | 16.961 | 0.076 |
| Gram | 361 | 0.290 | 0.404 | 0.058 |
| Jowar | 263 | 0.350 | 0.459 | 0.008 |
| Dry chillies | 129 | 1.179 | 1.934 | -0.122 |
| Bajra | 280 | 0.547 | 0.657 | 0.318 |
| Soyabean | 186 | 0.415 | 0.499 | -0.077 |

Negative R² for Urad, dry chillies and Soyabean means those crop estimates are weak. The overall comparison does not justify treating every crop as reliable.

## Feature ablations

| Random Forest inputs | Validation score | 2019 backtest score |
| --- | ---: | ---: |
| weather_only | 0.3709 | 0.4535 |
| weather_ndvi | 0.3666 | 0.4474 |
| weather + NDVI/EVI/LST/NDRE | 0.3664 | 0.4475 |

The extra EVI/LST/NDRE columns give no clear incremental benefit over weather plus NDVI: validation is almost unchanged and the retrospective backtest is slightly worse. Collecting the columns is not evidence that they improve yield accuracy.

## Coverage and evidence

Accepted labels: 17,895; checked district/weather reference points: 480; all 16 crops. Quarantined label/season rows: 15,148; unresolved geographic pairs: 207; incomplete accepted weather windows: 0.

54 monthly satellite batches × 480 locations = 25,920 records, July 2015–December 2019. Observed fractions across these acquisition records: NDVI/EVI 95.18%, LST 69.48%, NDRE 85.64%. These are acquisition coverage, not model accuracy or data freshness. Per-crop/year availability and counts are saved in the run evaluation JSON.

NASA January 2019 Ludhiana monthly values were independently fetched and exactly matched the preserved cache across all nine variables. One independently calculated Sentinel-2 pixel NDRE matched Earth Engine exactly. These sample checks do not authenticate every historical request. Original weather CSVs lack embedded coordinate manifests; locations were reconstructed from the preserved fetcher and checked against boundaries.

APY agricultural starting years were verified against official state totals. Punjab cane is retained; unresolved Chhattisgarh sugarcane rows are quarantined. The owner identifies India Data Portal as the upstream source and a cleaned Kaggle derivative as the download; the exact Kaggle version and cleaning lineage remain unverified. [Data sources and processing limits](data-provenance.md).

Other limits: fixed reporting seasons, contemporary boundaries, district point buffers without crop masks, missing satellite observations, TOA atmospheric comparability, and 8/16-day composite support extending up to 15 days past nominal reporting boundaries. The demo replays supported historical observations, with the actual reporting window and composite support disclosed.

Detailed evidence: [evaluation JSON](../artifacts/runs/20261021T223804Z/evaluation.json), [saved predictions](../artifacts/runs/20261021T223804Z/predictions.csv), [2019 Wheat QGIS render](gis/wheat_backtest.png), [QGIS project](gis/farm_yield.qgz).

Earlier candidates were not released: one failed bit-exact parallel prediction parity; another was invalidated after the sugarcane unit audit. The serving manifest refers only to the corrected verified run.
