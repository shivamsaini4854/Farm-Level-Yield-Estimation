import pandas as pd

def run_analysis():
    try:
        # Loading the cleaned CSV
        df = pd.read_csv("saharanpur_sugarcane_yield.csv")
        
        # Current Dashboard Stats
        current_ndvi = 0.3531 
        latest_historical_yield = df['Yield'].iloc[-1] # Gets 84.48

        print(f"✓ Success! Data loaded.")
        print(f"Latest Saharanpur Yield: {latest_historical_yield} Tonnes/Hectare")
        print(f"Current Farm NDVI: {current_ndvi}")

        # Basic Prediction logic for your report
        # If NDVI is moderate (0.35), yield might be slightly under the peak
        predicted_yield = latest_historical_yield * (current_ndvi / 0.4) 
        
        print(f"--- PREDICTION ---")
        print(f"Estimated Yield for 2026: {predicted_yield:.2f} Tonnes/Hectare")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_analysis()