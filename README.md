# Farm Yield Estimation

A Flask research dashboard for completed-season crop-yield estimation in India, trained on district-level labels. A map pin does not establish accuracy for an individual field.

## Current status

The application, data and artifacts have been separated into packages and directories. The original model and reports are preserved under `artifacts/baseline/legacy/`. Their historical scores used flawed evaluation and are not fresh evidence of model quality.

The web interface and `/health` run without database or satellite access. Prediction deliberately returns `503 model_unavailable` until a verified schema-version-2 bundle is promoted. `/ready` reports model, database and session-key readiness separately. National feature acquisition, new model results, live persistence, QGIS output and public deployment must be verified before they are described as complete.

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

Earth Engine credentials and an authorised `GEE_PROJECT` are needed for satellite acquisition. Authenticate on the machine where acquisition runs; use provider-supported credentials in deployment secrets. Runtime authentication has to be tested, not inferred from installed packages.

## Offline checks

```powershell
python -X utf8 -m unittest discover -s tests -v
node --check farm_yield/static/js/app.js
```

Tests mock external services. Syntax alone does not prove valid predictions or available APIs.

## API

- `GET /health`: process health without external calls.
- `GET /ready`: `200` only when verified model, database schema and configured session signing are ready; otherwise `503` with boolean checks.
- `POST /api/fetch_ndvi`: JSON `lat`, `lon`, `crop`; latest completed season only. Validates coordinates and the supported crop set. Returns model version, observation period, feature availability, evidence limits and prediction ID on success.
- `GET /api/predictions`: at most 20 predictions belonging to the current signed browser session.
- `POST /api/ingest`: administrator-only, `X-Admin-Key` header. JSON contains `dataset_version` and 1?100 monthly observation `records`; the body limit is 256 KiB. Each record contains state/district names, first-of-month ISO `month`, observed `days`, weather variables defined in `farm_yield/features.py`, and nullable NDVI/EVI/LST/NDRE. Repeating the same version and record is idempotent.
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

The older acquisition modules retain their original dataset conventions and are not evidence that new historical features have been collected. Do not refetch national history merely to check syntax. Baseline artifacts are immutable; training must write a new run and pass evaluation/schema gates before promotion.

## Deployment

`render.yaml` specifies a free Render Python web service with Gunicorn and process health checks. Configure database and Earth Engine secrets through the provider, never in the repository. A configuration file is not proof of deployment; publish a URL only after the real service responds and its limitations are measured. Keep durable history in the remote database rather than ephemeral local files.

## Evaluation limits

Preserve temporal separation and train-only preprocessing. Report per-crop errors in tonnes/hectare, sample counts, missing coverage and dataset/artifact versions. Years inspected in previous experiments cannot be called a pristine unseen test. New satellite columns require real historical observations, consistent processing levels/masks/scales and feature ablations before claiming they help.
