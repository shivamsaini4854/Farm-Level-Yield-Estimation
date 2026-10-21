import requests
import datetime
import mysql.connector
from mysql.connector import Error
from farm_yield.acquisition.fetch_soil_smap import get_blended_soil_report
import os

from dotenv import load_dotenv
from farm_yield.paths import ENV_FILE

load_dotenv(ENV_FILE)  # loads the .env file

DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME'),
    'port': int(os.getenv('DB_PORT', 3306))
}

def save_weather_to_db(farmer_id, temp, rain, humidity, soil_moisture):
    connection = None  # guard against UnboundLocalError in finally block
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            cursor = connection.cursor()

            insert_query = """
            INSERT INTO WeatherData (farmer_id, temperature_c, rainfall_mm, humidity_pct, soil_moisture)
            VALUES (%s, %s, %s, %s, %s)
            """

            if soil_moisture is None:
                soil_moisture = 0.0

            record = (farmer_id, temp, rain, humidity, soil_moisture)
            cursor.execute(insert_query, record)
            connection.commit()

            print(f"✅ Successfully saved weather data to the database for Farmer ID: {farmer_id}")

    except Error as e:
        print(f"❌ Failed to insert record into MySQL table: {e}")
    finally:
        if connection and connection.is_connected():  # safe guard — won't crash if connect() failed
            cursor.close()
            connection.close()


def get_agricultural_weather(lat, lon, farmer_id):
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,precipitation"
            f"&hourly=soil_moisture_0_to_1cm"
            f"&forecast_days=1"
            f"&timezone=Asia%2FKolkata"
        )

        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        current = data.get('current', {})
        hourly = data.get('hourly', {})

        temp = current.get('temperature_2m', 0)
        humidity = current.get('relative_humidity_2m', 0)
        rainfall = current.get('precipitation', 0.0)

        current_time_iso = current.get('time', 'Unknown')
        current_hour_index = datetime.datetime.now().hour
        raw_soil_array = hourly.get('soil_moisture_0_to_1cm', [])

        print(f"\n--- DEBUG HOOD ---")
        print(f"API Current Time: {current_time_iso}")
        print(f"Target Hour Index: {current_hour_index}")
        print(f"Raw Soil Array (first 5 hours): {raw_soil_array[:5]}")
        print(f"------------------\n")

        raw_soil = 0.0
        if len(raw_soil_array) > current_hour_index:
            raw_soil = raw_soil_array[current_hour_index]

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


if __name__ == "__main__":
    LAT = 30.107108
    LON = 77.098991
    FARMER_ID = 1

    # Step 1: Get weather + surface soil from Open-Meteo
    weather = get_agricultural_weather(LAT, LON, FARMER_ID)

    # Step 2: Get blended soil report (NASA + Open-Meteo)
    soil_report = get_blended_soil_report(LAT, LON)

    # Step 3: Pull root zone moisture from NASA (best available)
    nasa_data = soil_report.get("nasa")
    root_zone = nasa_data.get("root_zone_moisture_pct") if nasa_data else None

    print(f"Root Zone Moisture (NASA): {root_zone}%")

    # Step 4: Save to DB — use NASA root zone if available, else fall back to Open-Meteo surface
    if weather:
        save_weather_to_db(
            FARMER_ID,
            weather["temperature"],
            weather["rainfall"],
            weather["humidity"],
            root_zone if root_zone is not None else weather["soil_moisture"]
        )