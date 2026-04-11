from flask import Flask, render_template, request, jsonify
import mysql.connector
import datetime
import pandas as pd

from fetch_weather import get_agricultural_weather
from fetch_satellite import get_ndvi

app = Flask(__name__)
# --- MULTI-CROP BASELINE DICTIONARY (Average Yield in T/Ha for North India) ---
CROP_BASELINES = {
    "Sugarcane": 84.48,  
    "Wheat": 4.5,        
    "Rice": 4.0,         
    "Maize": 3.2         
}
# This is the primary route that loads the UI and handles live weather updates
@app.route('/', methods=['GET', 'POST'])
def home():
    weather_data = None
    # Create empty variables to store the coordinates
    submitted_lat = None
    submitted_lon = None

    if request.method == 'POST':
        submitted_lat = request.form.get('latitude')
        submitted_lon = request.form.get('longitude')
        
        if submitted_lat and submitted_lon:
            weather_data = get_agricultural_weather(float(submitted_lat), float(submitted_lon), 1)

    # Pass the coordinates BACK to the HTML so the map remembers them!
    return render_template('index.html', weather=weather_data, submitted_lat=submitted_lat, submitted_lon=submitted_lon)

# --- DYNAMIC SATELLITE API ROUTE ---
@app.route('/api/fetch_ndvi', methods=['POST'])
def api_fetch_ndvi():
    try:
        data = request.json
        farm_lat = data.get('lat')
        farm_lon = data.get('lon')
        farm_crop = data.get('crop', 'Sugarcane') # NEW: Catch the crop!

        if not farm_lat or not farm_lon:
            return jsonify({"error": "Coordinates missing"}), 400

        # NEW: Look up the baseline for the specific crop the user selected!
        target_baseline = CROP_BASELINES.get(farm_crop, 84.48)

        end = datetime.datetime.now().strftime('%Y-%m-%d')
        start = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime('%Y-%m-%d')

        ndvi_val = get_ndvi(float(farm_lon), float(farm_lat), start, end)

        if ndvi_val is None:
            return jsonify({"error": "Cloud coverage too high"}), 500

        # NEW: Use the dynamic target_baseline here instead of latest_baseline
        predicted_yield = target_baseline * (ndvi_val / 0.4)
        prediction_rounded = round(predicted_yield, 2)

        return jsonify({
            "ndvi": round(ndvi_val, 4),
            "prediction": prediction_rounded,
            "baseline": target_baseline, # NEW: Send the baseline back
            "status": "success"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
if __name__ == '__main__':
    app.run(debug=True)