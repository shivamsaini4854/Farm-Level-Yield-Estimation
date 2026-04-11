import requests
import datetime
import mysql.connector
from mysql.connector import Error

# --- DATABASE CONNECTION DETAILS ---
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '12231691223178',
    'database': 'FarmYieldSystem'
}

def save_weather_to_db(farmer_id, temp, rain, humidity, soil_moisture):
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            cursor = connection.cursor()
            
            # SQL Insert Query
            insert_query = """
            INSERT INTO WeatherData (farmer_id, temperature_c, rainfall_mm, humidity_pct, soil_moisture)
            VALUES (%s, %s, %s, %s, %s)
            """
            
            # Handle the Open-Meteo 'None' soil moisture issue gracefully
            if soil_moisture is None:
                soil_moisture = 0.0 
                
            record = (farmer_id, temp, rain, humidity, soil_moisture)
            cursor.execute(insert_query, record)
            connection.commit()
            
            print(f"✅ Successfully saved weather data to the database for Farmer ID: {farmer_id}")
            
    except Error as e:
        print(f"❌ Failed to insert record into MySQL table: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def get_agricultural_weather(lat, lon, farmer_id):
    try:
        # Open-Meteo API URL asking for specific agricultural variables
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,precipitation,soil_moisture_0_to_7cm&timezone=Asia%2FKolkata"
        
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        current = data.get('current', {})
        
        # Parse the specific variables
        temp = current.get('temperature_2m', 0)
        humidity = current.get('relative_humidity_2m', 0)
        rainfall = current.get('precipitation', 0.0) # Precise rainfall in mm
        
        # Grab soil moisture safely
        raw_soil = current.get('soil_moisture_0_to_7cm')
        
        # ADD THIS IF STATEMENT: If the API sends null (None), fallback to 0.0
        if raw_soil is None:
            raw_soil = 0.0
            
        soil_moisture = round(raw_soil * 100, 1)

        weather_dict = {
            "farmer_id": farmer_id,
            "temperature": temp,
            "humidity": humidity,
            "rainfall": rainfall,
            "soil_moisture": soil_moisture,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        print(f"✓ Weather Fetched: {weather_dict}")
        return weather_dict

    except requests.exceptions.RequestException as e:
        print(f"✗ Weather API Error: {e}")
        return None

# Quick test if you run this file directly
if __name__ == "__main__":
    get_agricultural_weather(30.0289, 77.1462, 1)