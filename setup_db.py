import mysql.connector
from mysql.connector import Error

def create_database_and_tables():
    try:
        # 1. Connect to the MySQL Server
        connection = mysql.connector.connect(
            host='localhost',
            user='root',
            password='12231691223178'
        )
        
        if connection.is_connected():
            cursor = connection.cursor()
            
            # 2. Create the Database
            cursor.execute("CREATE DATABASE IF NOT EXISTS FarmYieldSystem")
            cursor.execute("USE FarmYieldSystem")
            
            # 3. Create the Farmers Table
            farmers_table = """
            CREATE TABLE IF NOT EXISTS Farmers (
                farmer_id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100),
                contact VARCHAR(15),
                farm_location_lat DECIMAL(10, 8),
                farm_location_long DECIMAL(11, 8),
                farm_area_hectares DECIMAL(5, 2)
            )
            """
            cursor.execute(farmers_table)
            
            # 4. Create the WeatherData Table
            weather_table = """
            CREATE TABLE IF NOT EXISTS WeatherData (
                weather_id INT AUTO_INCREMENT PRIMARY KEY,
                farmer_id INT,
                fetch_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                temperature_c DECIMAL(5, 2),
                rainfall_mm DECIMAL(5, 2),
                humidity_pct DECIMAL(5, 2),
                soil_moisture DECIMAL(5, 3),
                FOREIGN KEY (farmer_id) REFERENCES Farmers(farmer_id) ON DELETE CASCADE
            )
            """
            cursor.execute(weather_table)
            
            print("✅ Backend Setup Complete! Database and Tables created successfully.")
            
    except Error as e:
        print(f"❌ Error while connecting to MySQL: {e}")
        
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

if __name__ == '__main__':
    create_database_and_tables()