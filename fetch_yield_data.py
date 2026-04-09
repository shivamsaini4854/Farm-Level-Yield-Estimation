from datagovindia import DataGovIndia
import pandas as pd

# 1. Initialize with your API key
API_KEY = "579b464db66ec23bdd000001f540892bf7114ade62cb5da2ee7efc11"
datagovin = DataGovIndia(API_KEY)

# 2. Use the updated 'search' method
print("Searching for yield datasets...")
results = datagovin.search("Area Production Yield")

# 3. Identify and Download
if not results.empty:
    print(results[['title', 'index_name']].head())
    
    # We will pull the main APY resource (usually the first one)
    resource_id = results.iloc[0]['index_name'] 
    print(f"Downloading Resource: {resource_id}...")
    
    # Use the updated 'get_resource' method
    data = datagovin.get_resource(resource_id)
    data.to_csv("historical_yield_india.csv", index=False)
    print("✓ Full India dataset saved!")
else:
    print("No datasets found. Check your API key or search term.")