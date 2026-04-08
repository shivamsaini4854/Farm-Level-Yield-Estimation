import ee

def get_ndvi(lon, lat, start_date, end_date):
    """
    Fetches Sentinel-2 imagery for a specific point and calculates the mean NDVI.
    """
    try:
        # Initialize with your specific project ID
        ee.Initialize(project='madd-1eddf')
        
        # Define the point of interest (Note: Earth Engine uses [Longitude, Latitude])
        point = ee.Geometry.Point([lon, lat])
        
        # Load Sentinel-2 Surface Reflectance data
        collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
            .filterBounds(point) \
            .filterDate(start_date, end_date) \
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)) # Filter out heavy clouds
        
        # Create a single composite image using the median of the collection
        image = collection.median()
        
        # Calculate NDVI: (NIR - Red) / (NIR + Red) -> (Band 8 - Band 4)
        ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
        
        # Extract the exact NDVI numerical value at our farm's coordinate
        ndvi_value = ndvi.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=point,
            scale=10 # Sentinel-2 resolution is 10 meters per pixel
        ).getInfo()
        
        return ndvi_value.get('NDVI')
        
    except ee.EEException as e:
        print(f"Earth Engine Error: {e}")
        return None

if __name__ == "__main__":
    # Test Coordinates for Farmer ID: 1
    test_lon = 77.14620000 
    test_lat = 30.02890000 
    
    # check the data for the past month
    start = '2026-03-01'
    end = '2026-04-08'
    
    print(f"Fetching Sentinel-2 NDVI data for Coordinates: [{test_lon}, {test_lat}]...")
    result = get_ndvi(test_lon, test_lat, start, end)
    
    if result is not None:
        print(f"SUCCESS! Calculated NDVI: {result:.4f}")
    else:
        print("Failed to retrieve NDVI data. Check coordinates or date range.")