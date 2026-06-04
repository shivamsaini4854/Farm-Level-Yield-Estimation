# Farm-Level Yield Estimation

Farm-Level Yield Estimation is a Flask-based AgriTech dashboard for estimating crop yield at a selected farm location in India. The application combines a trained scikit-learn regression model with live farm coordinates, Sentinel-2 NDVI from Google Earth Engine, and seasonal weather/soil variables from NASA POWER.

The project was built as a B.Tech farm intelligence system. It supports map-based farm selection, crop-aware season windows, live satellite and weather fetching, and a baseline machine-learning pipeline trained on district-level crop, climate, soil, and vegetation data.

## Features

- Interactive web dashboard built with Flask, Jinja, HTML, CSS, JavaScript, and Leaflet.
- India-only farm selection with map search, click-to-place pin behavior, and coordinate validation.
- Crop selector for 16 major Indian crops.
- Season-aware inference for Kharif, Rabi, and Whole Year crops.
- Live Sentinel-2 NDVI fetching through Google Earth Engine.
- Seasonal NASA POWER weather aggregation for temperature, rainfall, humidity, wind, solar radiation, and soil moisture.
- Trained Gradient Boosting Regressor for yield prediction in tonnes per hectare.
- Fallback prediction path if model artifacts fail to load.
- MySQL/TiDB connection support for farmer and weather storage.
- Reproducible data merge and training pipeline.

## Tech Stack

- Backend: Python, Flask
- Frontend: HTML, CSS, JavaScript, Jinja templates, Leaflet
- Machine learning: pandas, NumPy, scikit-learn, joblib
- Satellite data: Google Earth Engine, Sentinel-2, MODIS NDVI
- Weather and soil data: NASA POWER, Open-Meteo helper scripts
- Database: MySQL-compatible cloud database, tested with TiDB

## Project Structure

```text
Farm-Level-Yield-Estimation/
|-- app.py                         # Main Flask app and live inference API
|-- templates/
|   `-- index.html                 # Dashboard template
|-- static/
|   |-- css/styles.css             # Dashboard styling
|   `-- js/app.js                  # Map, search, crop selection, API calls
|-- merge_and_train.py             # Merge, feature engineering, model training
|-- fetch_nasa_power.py            # Historical NASA POWER weather/soil fetcher
|-- fetch_ndvi_historical.py       # Historical MODIS NDVI batch 1 fetcher
|-- fetch_ndvi_batch2.py           # Historical MODIS NDVI batch 2 fetcher
|-- fetch_satellite.py             # Live Sentinel-2 NDVI and SMAP helper
|-- fetch_weather.py               # Current weather helper and DB save helper
|-- fetch_soil_smap.py             # NASA/Open-Meteo soil moisture helper
|-- setup_db.py                    # Local MySQL schema setup helper
|-- APY.csv                        # Raw crop area/production/yield dataset
|-- nasa_power_seasonal.csv        # Seasonal NASA POWER aggregates
|-- ndvi_historical_all_india.csv  # Historical MODIS NDVI aggregates
|-- merged_dataset.csv             # Final merged training dataset
|-- yield_model.pkl                # Trained best model
|-- scaler.pkl                     # Fitted StandardScaler artifact
|-- model_metadata.json            # Feature columns, crop list, metrics
|-- training_report.txt            # Model evaluation report
|-- requirements.txt               # Python dependencies
`-- project_state.txt              # Development checkpoint notes
```

## Supported Crops

The current model and UI support:

- Rice
- Maize
- Moong(Green Gram)
- Urad
- Groundnut
- Wheat
- Rapeseed &Mustard
- Sugarcane
- Arhar/Tur
- Potato
- Onion
- Gram
- Jowar
- Dry chillies
- Bajra
- Soyabean

## Data Sources

### Crop Yield Labels

- Source file: `APY.csv`
- Coverage: district-wise crop area, production, and yield records for India
- Training crop subset: top 16 crops listed above
- Target column: `yield_t_ha`

### Historical Weather and Soil

- Source: NASA POWER API
- Output file: `nasa_power_seasonal.csv`
- Variables include mean/min/max temperature, rainfall, humidity, wind speed, solar radiation, root-zone soil moisture, surface soil moisture, and season length.
- The fetcher stores raw per-district daily files under `nasa_power_raw/`.

### Historical NDVI

- Source: Google Earth Engine MODIS `MODIS/061/MOD13A3`
- Output file: `ndvi_historical_all_india.csv`
- MODIS data starts from 2000, so pre-2000 NDVI is handled through imputation during training.

### Live Inference Data

- Sentinel-2 NDVI: Google Earth Engine `COPERNICUS/S2_SR_HARMONIZED`
- Weather and soil: NASA POWER daily point API
- Location search: Nominatim/OpenStreetMap from the browser
- Map tiles: CARTO/OSM through Leaflet

## Model Summary

The final trained model is a Gradient Boosting Regressor saved in `yield_model.pkl`.

Training uses a temporal split instead of a random split:

- Train years: 1997-2017
- Test years: 2018-2020
- Target: yield in tonnes per hectare
- Feature count: 41 columns from weather, engineered climate/soil/NDVI features, crop one-hot columns, season one-hot columns, and area

Model comparison from `model_metadata.json`:

| Model | MAE | RMSE | R2 |
| --- | ---: | ---: | ---: |
| Ridge | 2.9773 | 7.0267 | 0.7890 |
| Random Forest | 1.8208 | 5.0538 | 0.8908 |
| Gradient Boosting | 1.8144 | 4.8341 | 0.9001 |

Important note: the overall R2 is influenced by high-yield crops such as Sugarcane. Per-crop metrics in `training_report.txt` and `model_metadata.json` should be used for honest crop-level evaluation.

## Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Farm-Level-Yield-Estimation
```

### 2. Create and Activate a Virtual Environment

Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

The application imports `python-dotenv` and the satellite helpers import `earthengine-api`. If those are not already installed in your environment, install them too:

```bash
pip install python-dotenv earthengine-api
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```env
DB_HOST=your-database-host
DB_PORT=4000
DB_USER=your-database-user
DB_PASSWORD=your-database-password
DB_NAME=your-database-name
```

The Flask app expects the TiDB/MySQL SSL certificate at:

```text
isrgrootx1.pem
```

Do not commit `.env` or private certificates.

### 5. Authenticate Google Earth Engine

The live NDVI code uses Google Earth Engine project `madd-1eddf`.

```bash
earthengine authenticate
```

Make sure the authenticated account has access to the configured Earth Engine project. If you use another project, update the project id in `fetch_satellite.py`, `fetch_ndvi_historical.py`, and `fetch_ndvi_batch2.py`.

## Running the App

Start the Flask server:

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

Typical demo flow:

1. Search for an Indian location, district, village, or landmark.
2. Move the pin onto the actual farm parcel.
3. Select a crop.
4. Click `Run yield analysis`.
5. Review predicted yield, NDVI, weather, and season-window outputs.

## API

### `GET /`

Renders the dashboard.

### `POST /api/fetch_ndvi`

Runs the live crop analysis for a farm point.

Request body:

```json
{
  "lat": 30.0289,
  "lon": 77.1462,
  "crop": "Wheat"
}
```

Successful response:

```json
{
  "status": "success",
  "ndvi": 0.5123,
  "prediction": 4.12,
  "crop": "Wheat",
  "season": "Rabi",
  "season_status": "completed",
  "model": "Gradient Boosting",
  "weather": {
    "temp": 19.4,
    "rainfall": 123.5,
    "humidity": 66.7,
    "soil": 45.2,
    "days": 182
  },
  "season_window": {
    "start": "Oct 01, 2025",
    "end": "Mar 31, 2026"
  }
}
```

Other possible statuses:

- `not_started`: crop season has not begun yet.
- `data_pending`: NASA POWER data is not yet available for the beginning of the season.
- Error response: invalid coordinates, unsupported location, unavailable weather, or external API failure.

## Training Pipeline

To rebuild the merged dataset and train the model:

```bash
python merge_and_train.py
```

Required input files:

- `APY.csv`
- `nasa_power_seasonal.csv`
- `ndvi_historical_all_india.csv`

Generated output files:

- `merged_dataset.csv`
- `yield_model.pkl`
- `scaler.pkl`
- `model_metadata.json`
- `training_report.txt`

The training script performs:

1. Crop filtering to the supported 16 crops.
2. APY + NASA POWER merge on state, district, season, and crop year.
3. NDVI left join on state, district, crop, season, and crop year.
4. Yield outlier capping per crop.
5. Weather, soil, heat, aridity, GDD, NDVI, crop, and season feature engineering.
6. Temporal train/test split.
7. Ridge, Random Forest, and Gradient Boosting model comparison.
8. Best model and metadata export.

## Data Fetching Scripts

### Historical NASA POWER

Fetch all configured districts:

```bash
python fetch_nasa_power.py
```

Safer low-concurrency mode:

```bash
python fetch_nasa_power.py --workers 4 --request-concurrency 1 --min-request-interval 1.5
```

Aggregate already-fetched raw files:

```bash
python fetch_nasa_power.py --aggregate
```

### Historical MODIS NDVI

Batch 1:

```bash
python fetch_ndvi_historical.py
```

Fetch a single state:

```bash
python fetch_ndvi_historical.py --state "Uttar Pradesh"
```

Merge batch outputs:

```bash
python fetch_ndvi_historical.py --merge
```

Batch 2:

```bash
python fetch_ndvi_batch2.py
```

### Live Helpers

```bash
python fetch_satellite.py
python fetch_weather.py
python fetch_soil_smap.py
```

These scripts are useful for testing external APIs independently from the Flask app.

## Database Setup

The production app reads database credentials from `.env` and connects over SSL.

`setup_db.py` is a local MySQL helper that creates:

- `Farmers`
- `WeatherData`

Before using it, update the local MySQL credentials inside `setup_db.py` or adapt it to use `.env`.

```bash
python setup_db.py
```

## Known Limitations

- Historical NDVI is district-centroid based, while live inference uses the selected farm coordinate.
- MODIS NDVI starts in 2000, so 1997-1999 NDVI values are imputed during training.
- NASA POWER daily data usually has a processing lag of several days.
- Some districts are missing from historical weather coverage because of APY naming mismatches.
- Pulse crops have weaker per-crop performance and need additional soil type and irrigation features.
- `setup_db.py` contains local development credentials and should be sanitized before sharing publicly.
- External network access is required for live NDVI, NASA POWER, map tiles, and search.

## Roadmap

- Expand historical NDVI coverage to remaining Indian states.
- Add soil type features from NBSS&LUP or similar soil datasets.
- Add irrigation access flags from district-level agricultural datasets.
- Evaluate XGBoost/LightGBM with automated hyperparameter tuning.
- Add time-series modeling for sequential NDVI and weather signals.
- Persist live predictions and farmer feedback for future retraining.
- Add authenticated REST API versioning for deployment.
- Add spatial visualizations for district-level model performance and yield maps.

## Security Notes

- Keep `.env` out of version control.
- Keep database certificates and private credentials out of commits.
- Do not expose `debug=True` in production.
- Rotate any credentials that were ever committed or shared.

## Project Status

Current checkpoint from `project_state.txt`: mentor demo ready for the Semester 6 foundation, data, and baseline ML phase.

