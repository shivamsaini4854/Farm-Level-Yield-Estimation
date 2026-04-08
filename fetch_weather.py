import requests
import pandas as pd

def get_agricultural_weather(lat, lon):
    print(f"Fetching weather data for Coordinates: {lat}, {lon}...\n")
    
    # Open-Meteo API endpoint for historical and current weather
    # We are pulling temperature, rain, and soil moisture
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,rain&hourly=soil_moisture_0_to_7cm&timezone=auto"
    
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        
        # Extracting the current data
        current = data['current']
        temp = current['temperature_2m']
        rain = current['rain']
        humidity = current['relative_humidity_2m']
        
        # Extracting soil moisture (taking the most recent hourly data)
        soil_moisture = data['hourly']['soil_moisture_0_to_7cm'][0]
        
        print("--- Live Farm Weather Data ---")
        print(f"Temperature: {temp}°C")
        print(f"Rainfall: {rain} mm")
        print(f"Humidity: {humidity}%")
        print(f"Surface Soil Moisture: {soil_moisture} m³/m³")
        print("------------------------------")
        
        return {
            "temperature": temp,
            "rain": rain,
            "humidity": humidity,
            "soil_moisture": soil_moisture
        }
    else:
        print("Failed to fetch data. Check your connection or coordinates.")
        return None

if __name__ == "__main__":
    # Test coordinates (Example: Radaur, Yamunanagar - near your institute)
    test_lat = 30.0289
    test_lon = 77.1462
    
    weather_data = get_agricultural_weather(test_lat, test_lon)