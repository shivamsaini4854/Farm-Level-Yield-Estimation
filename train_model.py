import pandas as pd
from sklearn.ensemble import RandomForestRegressor
import mysql.connector
import joblib

# 1. Fetch data from your MySQL
db = mysql.connector.connect(host="localhost", user="root", password="your_password", database="FarmYieldSystem")
query = "SELECT temperature_c, rainfall_mm, humidity_pct, soil_moisture, ndvi_score, actual_yield FROM WeatherData"
df = pd.read_sql(query, db)

# 2. Split Features and Target
X = df[['temperature_c', 'rainfall_mm', 'humidity_pct', 'soil_moisture', 'ndvi_score']]
y = df['actual_yield']

# 3. Initialize and Train Baseline
model = RandomForestRegressor(n_estimators=100, random_state=42)
model.fit(X, y)

# 4. Save the model for Flask to use
joblib.dump(model, 'yield_model.pkl')
print("Baseline Model Trained and Saved!")