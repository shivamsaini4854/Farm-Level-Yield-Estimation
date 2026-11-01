# Semester 7 release status

Updated 2026-11-01. [Public demo](https://farm-yield-demo.onrender.com) · [evaluation](evaluation.md) · [verification record](verification.json).

This is a Resume/B.Tech research project. The demo estimates completed historical seasons using district labels. Its latest supported harvest year is 2019; individual-field and current-season accuracy are unverified.

| Roadmap card | Status | Evidence and remaining limits |
| --- | --- | --- |
| Advanced ML models | Done | Six candidates, frozen training/validation/backtest years, per-crop metrics, ablations, portable offline LSTM checkpoint, and verified Random Forest serving bundle. LSTM has the lowest offline error; RF is the best tabular candidate. |
| Feature engineering | Partial | All 54 monthly satellite batches completed for 480 checked district points; NDVI/EVI/LST/NDRE missingness and complete weather windows recorded. All 16 crops remain supported. 207 geographic pairs are unresolved; the cleaned Kaggle file's exact version and lineage are unverified. |
| REST API development | Done | Versioned predictions, provenance, descriptive alerts, bounded protected ingestion, invalid-input handling and honest unavailable states. Public prediction and ingestion round trips passed. |
| Database integration | Partial | TiDB TLS, transactional persistence, observation readback, idempotent ingestion, rollback tests and session-isolated history passed. Account tier and zero-spending limit remain unverified because browser control cannot reach the signed-in console. |
| Farmer dashboard (basic) | Done | Live search/prediction/history/district-map interactions and actual outline download passed. Candidate layout passed four viewports; deployed CSS/JS match the published candidate Git blobs. This is not a complete accessibility audit. |
| QGIS map integration | Done | Real QGIS 4.2.2 project and PNG export; 735 boundary features and 381 Wheat backtest features. Field outlines remain separate user drawings. |

Four cards are Done and two are Partial. Semester 6 and 8 roadmap statuses were not reassessed.

## Release evidence

[Measured 2026-11-01: `render deploys list srv-dbcj9cuq1p3s73c9itl0 --output json`] deployment `dep-dbjllt2vcj2c73f4c5t0` is live at commit `3457ef7dd5308f07c827d9a4ee9ef53df82427fb`. [Measured 2026-11-01: `render services --output json`] this web service uses plan `free`. TiDB billing is a separate, unresolved check.

[Measured 2026-11-01: public HTTP workflow, recorded in `verification.json`] health/readiness return 200; Ludhiana Wheat returns 3.10 t/ha with model `20261021T223804Z`; own-session history contains the prediction and another session is empty; invalid input returns 400; unauthenticated ingestion returns 401; authorised observation ingestion returns 201 and repeating it inserts zero rows; direct database readback matches; the Wheat map contains 381 districts. Prediction proof: `d8e37c62-df87-4755-b0c6-a5a2c58402a8`.

[Measured 2026-11-01: `python -X utf8 -m unittest discover -s tests -q`, exit 0] 25 tests passed, including all 16 crops through the real serving transformation with database writes mocked. Recursive AST parsing covered 29 Python files. `node --check farm_yield/static/js/app.js` and `node tests/dashboard_test.cjs` passed. Tests cover season alignment, missing observations, duplicate keys, train-only preprocessing, feature order, artifact hashes, prediction parity, API errors, rollback, history isolation, safe rendering, stale responses and outline/backtest isolation.

[Measured 2026-11-01: Playwright CLI browser interactions against the demo with candidate CSS/JS request routing] search, 3.10 t/ha prediction, history, district layer and actual GeoJSON download passed without page-script errors. The downloaded polygon is closed and valid. Screenshots were inspected; no horizontal overflow or off-screen controls at 1920×1080, 1440×900, 1366×768 or 390×844. The map stays 498 px high on desktop and 338 px on mobile. Published assets were independently fetched after deployment and matched Git blob SHA-256 hashes. A final repeat through browser control was unavailable: its browser host and native pipe could not connect.

## Remaining work and limits

- Verify the existing TiDB account's plan, current charges and monthly spending limit. No billing settings were changed.
- Resolve the 207 geographic matches only with defensible historical mappings. Full national coverage is not claimed.
- Recover the exact cleaned Kaggle version and transformation history if available. The project owner supplied the India Data Portal source URL; it returned HTTP 403 in the checked browser.
- Existing faint labels, small mobile Search target and help overlays remain accessibility limits. No WCAG compliance or visual-regression-baseline claim is made.
- Free-service cold starts can return an application-loading 503 before the app wakes. Current-season/farm-level accuracy and a pristine future-year holdout are not established. Some crop backtests have negative R², and extra EVI/LST/NDRE features show no clear gain over weather plus NDVI.
- Credentials removed from old source may remain in Git history; account-owner rotation has not been verified.
