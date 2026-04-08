import requests
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
    print(f"Fetching weather data for Coordinates: {lat}, {lon}...")
    
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,rain&hourly=soil_moisture_0_to_7cm&timezone=auto"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        
        temp = data['current']['temperature_2m']
        rain = data['current']['rain']
        humidity = data['current']['relative_humidity_2m']
        soil_moisture = data['hourly']['soil_moisture_0_to_7cm'][0]
        
        # Save to database
        save_weather_to_db(farmer_id, temp, rain, humidity, soil_moisture)
        
        # NEW: Return the data so Flask can use it!
        return {"temp": temp, "rain": rain, "humidity": humidity, "soil": soil_moisture}
        
    else:
        print("❌ Failed to fetch data from API.")
        return None