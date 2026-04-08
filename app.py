from flask import Flask, render_template, request, jsonify
import mysql.connector
import datetime

from fetch_weather import get_agricultural_weather
from fetch_satellite import get_ndvi

app = Flask(__name__)

# We added 'POST' to allow the website to send data (button clicks) to the server
@app.route('/', methods=['GET', 'POST'])
def home():
    weather_data = None

    if request.method == 'POST':
        # When the user clicks the button, fetch the live data for Farmer 1
        weather_data = get_agricultural_weather(30.0289, 77.1462, 1)

    # Pass the weather data to the HTML page
    return render_template('index.html', weather=weather_data)

# --- NEW SATELLITE API ROUTE ---
@app.route('/api/fetch_ndvi/<int:farmer_id>', methods=['GET'])
def api_fetch_ndvi(farmer_id):
    try:
        # Connect to DB 
        db = mysql.connector.connect(
            host="localhost", 
            user="root", 
            password="12231691223178", # <--- DONT FORGET TO PUT YOUR PASSWORD HERE
            database="FarmYieldSystem"
        )
        cursor = db.cursor(dictionary=True)
        
        # Get Farmer Coordinates
        cursor.execute("SELECT farm_location_lat, farm_location_long FROM Farmers WHERE farmer_id = %s", (farmer_id,))
        farmer = cursor.fetchone()
        
        if not farmer:
            return jsonify({"error": "Farmer not found"}), 404
            
        # Set Date Range (last 30 days)
        end = datetime.datetime.now().strftime('%Y-%m-%d')
        start = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
        
        # Call Earth Engine - FORCING FLOATS HERE
        lon = float(farmer['farm_location_long'])
        lat = float(farmer['farm_location_lat'])
        ndvi_val = get_ndvi(lon, lat, start, end)
        
        if ndvi_val is None:
            return jsonify({"error": "Cloud coverage too high or Earth Engine timeout"}), 500
            
        # Return to frontend
        return jsonify({
            "farmer_id": farmer_id,
            "ndvi": round(ndvi_val, 4),
            "status": "success"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)