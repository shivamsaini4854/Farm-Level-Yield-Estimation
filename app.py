from flask import Flask, render_template, request, jsonify
import mysql.connector
import datetime
import pandas as pd
import numpy as np
import os
import json
import joblib
import requests
from dotenv import load_dotenv

from fetch_weather import get_agricultural_weather
from fetch_satellite import get_ndvi

load_dotenv()

app = Flask(__name__)

# --- CONNECT TO THE CLOUD DATABASE ---
try:
    db_connection = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        ssl_ca="isrgrootx1.pem",
        ssl_verify_cert=True,
        ssl_verify_identity=True
    )
    print("✅ Successfully connected to the Cloud Database!")
except Exception as e:
    print(f"❌ Database connection failed: {e}")

# --- LOAD ML MODEL ---
try:
    model    = joblib.load("yield_model.pkl")
    scaler   = joblib.load("scaler.pkl")
    with open("model_metadata.json") as f:
        metadata = json.load(f)
    FEATURE_COLS = metadata["feature_columns"]
    USES_SCALER  = metadata.get("uses_scaler", False)
    print(f"✅ ML Model loaded: {metadata['model_name']}")
    ML_READY = True
except Exception as e:
    print(f"❌ ML Model load failed: {e}")
    ML_READY = False

# --- CROP SEASON DEFINITIONS ---
CROP_SEASONS = {
    "Sugarcane":          {"season": "Whole Year", "start": (1,  1),  "end": (12, 31), "wraps": False},
    "Wheat":              {"season": "Rabi",        "start": (10, 1),  "end": (3,  31), "wraps": True},
    "Rice":               {"season": "Kharif",      "start": (6,  1),  "end": (11, 30), "wraps": False},
    "Maize":              {"season": "Kharif",      "start": (6,  1),  "end": (10, 31), "wraps": False},
    "Bajra":              {"season": "Kharif",      "start": (6,  1),  "end": (10, 31), "wraps": False},
    "Jowar":              {"season": "Kharif",      "start": (6,  1),  "end": (10, 31), "wraps": False},
    "Groundnut":          {"season": "Kharif",      "start": (6,  1),  "end": (11, 30), "wraps": False},
    "Arhar/Tur":          {"season": "Kharif",      "start": (6,  1),  "end": (11, 30), "wraps": False},
    "Moong(Green Gram)":  {"season": "Kharif",      "start": (6,  1),  "end": (10, 31), "wraps": False},
    "Urad":               {"season": "Kharif",      "start": (6,  1),  "end": (10, 31), "wraps": False},
    "Soyabean":           {"season": "Kharif",      "start": (6,  1),  "end": (10, 31), "wraps": False},
    "Gram":               {"season": "Rabi",        "start": (10, 1),  "end": (3,  31), "wraps": True},
    "Rapeseed &Mustard":  {"season": "Rabi",        "start": (10, 1),  "end": (3,  31), "wraps": True},
    "Potato":             {"season": "Rabi",        "start": (10, 1),  "end": (3,  31), "wraps": True},
    "Onion":              {"season": "Rabi",        "start": (10, 1),  "end": (3,  31), "wraps": True},
    "Dry chillies":       {"season": "Kharif",      "start": (6,  1),  "end": (11, 30), "wraps": False},
}

INDIA_BOUNDS = {
    "min_lat": 6.0,
    "max_lat": 38.5,
    "min_lon": 67.0,
    "max_lon": 98.5,
}

INDIA_MAINLAND_POLYGON = [
    (23.5, 68.0), (24.8, 68.7), (26.6, 69.4), (29.0, 70.2), (31.8, 74.2),
    (34.2, 75.5), (35.8, 77.4), (35.8, 79.8), (34.0, 78.6), (31.8, 78.0),
    (30.1, 79.0), (28.2, 80.6), (27.0, 82.8), (26.1, 84.6), (25.7, 86.8),
    (25.5, 88.5), (24.5, 89.5), (23.0, 89.9), (21.7, 89.5), (20.6, 88.8),
    (21.0, 87.2), (20.7, 86.0), (19.7, 85.0), (19.0, 83.8), (18.3, 82.8),
    (17.3, 81.5), (16.1, 80.5), (15.0, 80.3), (13.5, 80.2), (12.1, 79.8),
    (10.8, 79.2), (9.1, 78.8), (8.1, 77.6), (8.2, 76.2), (9.2, 75.4),
    (10.6, 74.8), (12.2, 74.3), (13.8, 74.0), (15.2, 73.8), (17.0, 73.4),
    (18.6, 72.9), (20.0, 72.2), (21.1, 71.5), (22.0, 70.6), (22.8, 69.6),
    (23.3, 68.8)
]

INDIA_NORTHEAST_POLYGON = [
    (22.0, 88.0), (23.0, 88.6), (24.2, 89.8), (25.4, 90.8), (26.6, 91.8),
    (27.6, 92.8), (28.7, 94.0), (29.4, 95.2), (29.6, 96.6), (29.1, 97.6),
    (28.0, 97.9), (26.8, 97.6), (25.8, 96.9), (24.8, 96.0), (24.0, 95.0),
    (23.4, 94.0), (22.8, 93.0), (22.4, 92.0), (22.1, 90.8), (22.0, 89.2)
]

INDIA_ISLAND_BOXES = [
    {"min_lat": 6.0, "max_lat": 14.5, "min_lon": 92.0, "max_lon": 94.5},
    {"min_lat": 8.0, "max_lat": 13.8, "min_lon": 72.0, "max_lon": 74.0},
]


def normalize_longitude(lon):
    return ((lon + 180.0) % 360.0) - 180.0


def point_in_polygon(lat, lon, polygon):
    inside = False
    j = len(polygon) - 1

    for i in range(len(polygon)):
        yi, xi = polygon[i]
        yj, xj = polygon[j]

        intersects = ((xi > lon) != (xj > lon)) and (
            lat < (yj - yi) * (lon - xi) / ((xj - xi) or 1e-12) + yi
        )
        if intersects:
            inside = not inside
        j = i

    return inside


def is_within_india(lat, lon):
    if point_in_polygon(lat, lon, INDIA_MAINLAND_POLYGON):
        return True
    if point_in_polygon(lat, lon, INDIA_NORTHEAST_POLYGON):
        return True

    for box in INDIA_ISLAND_BOXES:
        if (
            box["min_lat"] <= lat <= box["max_lat"] and
            box["min_lon"] <= lon <= box["max_lon"]
        ):
            return True

    return False


def normalize_and_validate_coordinates(lat, lon, restrict_to_india=False):
    lat = float(lat)
    lon = normalize_longitude(float(lon))

    if not (-90.0 <= lat <= 90.0):
        raise ValueError("Latitude must be between -90 and 90.")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("Longitude must be between -180 and 180.")

    if restrict_to_india:
        if not (
            INDIA_BOUNDS["min_lat"] <= lat <= INDIA_BOUNDS["max_lat"] and
            INDIA_BOUNDS["min_lon"] <= lon <= INDIA_BOUNDS["max_lon"] and
            is_within_india(lat, lon)
        ):
            raise ValueError("Please select a location in India.")

    return lat, lon

def get_season_window(crop):
    today  = datetime.date.today()
    info   = CROP_SEASONS.get(crop)
    if not info:
        return None, None, None, "unknown"

    season = info["season"]
    sm, sd = info["start"]
    em, ed = info["end"]
    wraps  = info["wraps"]

    if wraps:
        if today.month >= sm:
            start = datetime.date(today.year, sm, sd)
            end   = datetime.date(today.year + 1, em, ed)
        else:
            start = datetime.date(today.year - 1, sm, sd)
            end   = datetime.date(today.year, em, ed)
    else:
        start = datetime.date(today.year, sm, sd)
        end   = datetime.date(today.year, em, ed)

    if today < start:
        status = "not_started"
    elif today > end:
        status = "completed"
    else:
        status = "active"

    return start, end, season, status


def fetch_season_weather_nasa(lat, lon, start_date, end_date):
    lat, lon = normalize_and_validate_coordinates(lat, lon)
    safe_end  = min(end_date, datetime.date.today() - datetime.timedelta(days=5))
    start_str = start_date.strftime("%Y%m%d")
    end_str   = safe_end.strftime("%Y%m%d")

    params_str = "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,RH2M,WS2M,ALLSKY_SFC_SW_DWN,GWETROOT,GWETTOP"
    url = (
        f"https://power.larc.nasa.gov/api/temporal/daily/point"
        f"?parameters={params_str}"
        f"&community=AG"
        f"&longitude={lon}&latitude={lat}"
        f"&start={start_str}&end={end_str}"
        f"&format=JSON"
    )

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data       = resp.json()
        param_data = data["properties"]["parameter"]

        dates = list(param_data["T2M"].keys())
        rows  = []
        for d in dates:
            row = {}
            for p in ["T2M","T2M_MAX","T2M_MIN","PRECTOTCORR","RH2M",
                      "WS2M","ALLSKY_SFC_SW_DWN","GWETROOT","GWETTOP"]:
                val = param_data.get(p, {}).get(d, -999)
                row[p] = None if val == -999 else val
            rows.append(row)

        df = pd.DataFrame(rows).dropna()
        if len(df) < 10:
            return None

        return {
            "temp_mean_c":           round(df["T2M"].mean(), 3),
            "temp_max_c":            round(df["T2M_MAX"].mean(), 3),
            "temp_min_c":            round(df["T2M_MIN"].mean(), 3),
            "rainfall_mm":           round(df["PRECTOTCORR"].sum(), 2),
            "humidity_pct":          round(df["RH2M"].mean(), 2),
            "wind_speed_ms":         round(df["WS2M"].mean(), 3),
            "solar_radiation_mj":    round(df["ALLSKY_SFC_SW_DWN"].sum(), 2),
            "soil_moisture_root":    round(df["GWETROOT"].mean(), 4),
            "soil_moisture_surface": round(df["GWETTOP"].mean(), 4),
            "season_days":           len(df),
        }
    except requests.HTTPError as e:
        print(f"NASA POWER HTTP error: {e}")
        return None
    except Exception as e:
        print(f"NASA POWER error: {e}")
        return None


def build_feature_vector(weather, crop, season, ndvi_val=None):
    feat = dict(weather)

    feat["temp_range_c"]            = feat["temp_max_c"] - feat["temp_min_c"]
    feat["soil_moisture_composite"] = (0.3 * feat["soil_moisture_surface"] +
                                       0.7 * feat["soil_moisture_root"])
    feat["gdd_proxy"]               = max(feat["temp_mean_c"] - 10, 0) * feat["season_days"]
    feat["heat_stress"]             = max(feat["temp_mean_c"] - 25, 0)
    safe_rad                        = feat["solar_radiation_mj"] if feat["solar_radiation_mj"] > 0 else 1
    feat["aridity_index"]           = min(feat["rainfall_mm"] / safe_rad, 10)
    feat["ndvi_season_mean"]        = ndvi_val if ndvi_val is not None else 0.35
    feat["ndvi_available"]          = 1 if ndvi_val is not None else 0

    all_crops = ["Rice","Maize","Moong(Green Gram)","Urad","Groundnut","Wheat",
                 "Rapeseed &Mustard","Sugarcane","Arhar/Tur","Potato","Onion",
                 "Gram","Jowar","Dry chillies","Bajra","Soyabean"]
    for c in all_crops:
        feat[f"crop_{c}"] = 1 if crop == c else 0

    all_seasons = ["Kharif","Rabi","Summer","Whole Year"]
    for s in all_seasons:
        feat[f"season_{s}"] = 1 if season == s else 0

    feat["area_ha"] = 100.0

    row = [feat.get(col, 0.0) for col in FEATURE_COLS]
    return np.array(row).reshape(1, -1)


def ml_predict(weather, crop, season, ndvi_val=None):
    X = build_feature_vector(weather, crop, season, ndvi_val)
    if USES_SCALER:
        X = scaler.transform(X)
    raw = float(model.predict(X)[0])
    BOUNDS = {
        "Rice":(0.3,5.0),"Maize":(0.3,8.5),"Moong(Green Gram)":(0.1,1.4),
        "Urad":(0.1,1.5),"Groundnut":(0.2,4.0),"Wheat":(0.3,5.5),
        "Rapeseed &Mustard":(0.1,2.2),"Sugarcane":(10,130),"Arhar/Tur":(0.1,2.5),
        "Potato":(1,35),"Onion":(1,35),"Gram":(0.1,2.1),"Jowar":(0.1,3.5),
        "Dry chillies":(0.1,8.0),"Bajra":(0.1,44),"Soyabean":(0.1,2.5),
    }
    lo, hi = BOUNDS.get(crop, (0, 200))
    return round(max(lo, min(hi, raw)), 2)


# --- ROUTES ---
@app.route('/', methods=['GET', 'POST'])
def home():
    weather_data  = None
    submitted_lat = None
    submitted_lon = None

    if request.method == 'POST':
        submitted_lat = request.form.get('latitude')
        submitted_lon = request.form.get('longitude')
        if submitted_lat and submitted_lon:
            try:
                submitted_lat, submitted_lon = normalize_and_validate_coordinates(
                    submitted_lat, submitted_lon, restrict_to_india=True
                )
                weather_data = get_agricultural_weather(submitted_lat, submitted_lon, 1)
            except ValueError:
                submitted_lat = None
                submitted_lon = None

    return render_template('index.html',
                           weather=weather_data,
                           submitted_lat=submitted_lat,
                           submitted_lon=submitted_lon)


@app.route('/api/fetch_ndvi', methods=['POST'])
def api_fetch_ndvi():
    try:
        data      = request.json
        farm_lat  = data.get('lat')
        farm_lon  = data.get('lon')
        farm_crop = data.get('crop', 'Sugarcane')

        if not farm_lat or not farm_lon:
            return jsonify({"error": "Coordinates missing"}), 400

        farm_lat, farm_lon = normalize_and_validate_coordinates(
            farm_lat, farm_lon, restrict_to_india=True
        )

        start_date, end_date, season_name, season_status = get_season_window(farm_crop)

        if season_status == "not_started":
            return jsonify({
                "status":  "not_started",
                "message": f"{farm_crop} season ({season_name}) hasn't started yet. Begins {start_date.strftime('%B %d')}.",
                "crop":    farm_crop,
                "season":  season_name,
            })

        ndvi_start = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
        ndvi_end   = datetime.datetime.now().strftime('%Y-%m-%d')
        ndvi_val   = get_ndvi(farm_lon, farm_lat, ndvi_start, ndvi_end)

        fetch_end = end_date if season_status == "completed" else datetime.date.today()
        weather   = fetch_season_weather_nasa(farm_lat, farm_lon, start_date, fetch_end)

        if weather is None:
            return jsonify({"error": "Weather data unavailable for this location"}), 500

        if ML_READY:
            prediction = ml_predict(weather, farm_crop, season_name, ndvi_val)
            model_used = metadata["model_name"]
        else:
            baselines  = {"Sugarcane":84.48,"Wheat":4.5,"Rice":4.0,"Maize":3.2}
            base       = baselines.get(farm_crop, 2.0)
            ndvi_v     = ndvi_val if ndvi_val else 0.35
            prediction = round(base * (ndvi_v / 0.4), 2)
            model_used = "heuristic_fallback"

        return jsonify({
            "status":        "success",
            "ndvi":          round(ndvi_val, 4) if ndvi_val else None,
            "prediction":    prediction,
            "crop":          farm_crop,
            "season":        season_name,
            "season_status": season_status,
            "model":         model_used,
            "weather": {
                "temp":     round(weather["temp_mean_c"], 1),
                "rainfall": round(weather["rainfall_mm"], 1),
                "humidity": round(weather["humidity_pct"], 1),
                "soil":     round(weather["soil_moisture_root"] * 100, 1),
                "days":     weather["season_days"],
            },
            "season_window": {
                "start": start_date.strftime("%b %d, %Y"),
                "end":   fetch_end.strftime("%b %d, %Y"),
            }
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
