# Farm Yield Estimation

A Flask research dashboard for completed-season crop-yield estimation in India, trained on district-level labels. A map pin does not establish accuracy for an individual field.

## Current status

The application, data and artifacts have been separated into packages and directories. The original model and reports are preserved under `artifacts/baseline/legacy/`. Their historical scores used flawed evaluation and are not fresh evidence of model quality.

The [public demo](https://farm-yield-demo.onrender.com) serves the verified Random Forest bundle `20261021T223804Z`. It covers 16 crops using 17,895 accepted district labels and 480 checked district reference points. Inputs include historical weather/soil, NDVI, EVI, LST and NDRE. The latest supported season ends in 2019; this is historical research, not a current-season forecast.

[Measured 2026-11-01: public HTTP workflow verified health/readiness, a 3.10 t/ha Wheat estimate for Ludhiana, isolated session history, protected/idempotent observation ingestion with database readback, and a 381-district Wheat map. Render CLI reports plan `free`.] Cold starts can delay the first request. The existing TiDB account's billing tier remains unverified.

Six models were compared on the same temporal split. LSTM had the lowest offline error; Random Forest is the best tabular candidate and keeps PyTorch outside deployment. Wheat's retrospective 2019 MAE is 0.693 t/ha across 381 district labels. Some crops have negative R², and the added EVI/LST/NDRE columns show no clear gain over weather plus NDVI. See the [complete evaluation](docs/evaluation.md) and [roadmap status](docs/release-status.md).

## Structure

- `app.py`: compatible development launcher and WSGI entry point.
- `farm_yield/`: Flask routes, shared features/seasons/paths, database access, acquisition, ML, templates and static assets.
- `data/raw/`: original APY labels, daily NASA cache and per-state NDVI data.
- `data/processed/`: seasonal joins and monthly features; `data/geo/`: geographic layers.
- `artifacts/baseline/legacy/`: unchanged original data/model/report artifacts and migration hashes.
- `artifacts/runs/`: versioned new training outputs; `artifacts/current.json`: promoted bundle pointer.
- `tests/`: focused offline checks.
- `docs/farm_yield_project_roadmap.html`: semester roadmap; `docs/archive/`: explicitly historical checkpoint.

## Setup

Use Python 3.13.5 and an isolated environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `.env` locally; never commit or print it. Set a stable random `SESSION_SECRET` and a separate `ADMIN_API_KEY`. TiDB/MySQL requires DB host, port, user, password and database. Connections verify TLS identity using `certs/isrgrootx1.pem` when present, or the installed CA bundle. Database setup creates only the new prediction/observation tables:

```powershell
python -m farm_yield.database
python app.py
```

Earth Engine credentials and an authorised `GEE_PROJECT` are needed only for satellite acquisition in the training environment. The web service uses the verified historical observation bundle and needs no Earth Engine credentials.

## Offline checks

```powershell
python -X utf8 -m unittest discover -s tests -v
node --check farm_yield/static/js/app.js
node tests/dashboard_test.cjs
```

Tests mock external services. Syntax alone does not prove valid predictions or available APIs.

## API

- `GET /health`: process health without external calls.
- `GET /ready`: `200` only when the verified model, district geography, database schema and session signing are ready; otherwise `503` with boolean checks.
- `POST /api/fetch_ndvi`: JSON `lat`, `lon`, `crop`; latest completed **supported historical** season only. Resolves the pin to a district and uses that district's verified reference-point observations from the serving bundle. It does not fetch a current-season forecast. Returns model version, observation period, feature availability, district, evidence limits and prediction ID on success.
- `GET /api/predictions`: at most 20 predictions belonging to the current signed browser session.
- `POST /api/ingest`: administrator-only, `X-Admin-Key` header. JSON contains `dataset_version` and 1–100 monthly observation `records`; the body limit is 256 KiB. Each record contains state/district names, first-of-month ISO `month`, observed `days`, weather variables defined in `farm_yield/features.py`, and nullable NDVI/EVI/LST/NDRE. Repeating the same version and record is idempotent.
- `GET /api/yield-map?crop=Wheat`: verified saved district predictions as GeoJSON; returns `503` until a map exists.

Errors distinguish invalid input (`400`), authentication (`401`), missing model/storage (`503`), and unavailable upstream observations (`502`). No heuristic yield is returned as successful ML output.

## Acquisition and training

Install additional packages only in the training environment:

```powershell
python -m pip install -r requirements-training.txt
python -m farm_yield.acquisition.fetch_nasa_power --help
python -m farm_yield.acquisition.fetch_ndvi_historical --help
python -m farm_yield.acquisition.fetch_ndvi_batch2 --help
```

The older acquisition modules retain their original dataset conventions. The audited replacement commands are:

```powershell
python -m farm_yield.acquisition.dataset
python -m farm_yield.acquisition.satellite_features --sample
python -m farm_yield.acquisition.satellite_features --verified-sample --workers 2
python -m farm_yield.ml.train --promote
```

Review and independently verify the sample before creating `sample_verification.json`; the national command requires that file. Completed monthly files are resumable. Model comparison requires every expected satellite batch, fits preprocessing on 2016–2017 only, selects on 2018, and reports 2019 as a retrospective backtest. All candidates receive the monthly information. See [data provenance](docs/data-provenance.md) for source uncertainty, starting-year semantics, quarantines and observation limits. Baseline artifacts remain immutable. Never refetch history or retrain merely to check syntax.

QGIS 4.2.2 exported a real project and maps on 2026-10-22 (`python-qgis.bat -m farm_yield.gis`): [project](docs/gis/farm_yield.qgz), [Wheat backtest](docs/gis/wheat_backtest.png), [coverage map](docs/gis/district_coverage.png). Per-crop GeoJSON layers preserve model version and district-level evidence. Field outlines exported by the dashboard are user drawings and contain no validated field-level prediction.

## Deployment

`render.yaml` specifies a free Render Python web service with Gunicorn and process health checks. Deployment uses the authorised private serving copy `SUMEET1000/farm-yield-demo`; it excludes raw historical datasets, training code, PyTorch and private working notes. Configure database/session/admin secrets through Render, never in the repository. Durable history lives in the remote database. Current deployed commit: `3457ef7`; verification evidence is in [release status](docs/release-status.md).

## Evaluation limits

Preserve temporal separation and train-only preprocessing. Report per-crop errors in tonnes/hectare, sample counts, missing coverage and dataset/artifact versions. Years inspected in previous experiments cannot be called a pristine unseen test. New satellite columns require real historical observations, consistent processing levels/masks/scales and feature ablations before claiming they help.
