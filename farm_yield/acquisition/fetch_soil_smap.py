import requests
import datetime


def get_nasa_power_soil(lat, lon):
    """
    Fetches soil moisture from NASA POWER API.
    NASA POWER blends MERRA-2 reanalysis + satellite data (including SMAP-informed parameters).
    No API key needed. Updates daily with ~1-2 day lag.

    Parameter used: GWETROOT — Root Zone Soil Wetness (0 to 1 scale)
    This represents moisture in the root zone (0–100 cm depth), which is more
    agriculturally meaningful than the 0–7cm surface layer.
    """
    today = datetime.date.today()
    # NASA POWER has ~1-2 day lag, so fetch yesterday to guarantee data
    target_date = today - datetime.timedelta(days=5)  # NASA POWER has ~3-5 day processing lag
    date_str = target_date.strftime("%Y%m%d")

    url = (
        f"https://power.larc.nasa.gov/api/temporal/daily/point"
        f"?parameters=GWETROOT,GWETTOP,PRECTOTCORR"
        f"&community=AG"                        # AG = Agriculture community — gives agri-specific params
        f"&longitude={lon}"
        f"&latitude={lat}"
        f"&start={date_str}"
        f"&end={date_str}"
        f"&format=JSON"
    )

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        params = data["properties"]["parameter"]

        gwetroot = params.get("GWETROOT", {}).get(date_str)   # Root zone soil wetness (0-1)
        gwettop = params.get("GWETTOP", {}).get(date_str)     # Top soil wetness (0-1)
        rainfall = params.get("PRECTOTCORR", {}).get(date_str) # Precipitation mm/day

        result = {
            "source": "NASA POWER (MERRA-2 + Satellite)",
            "date": target_date.strftime("%Y-%m-%d"),
            "root_zone_moisture_pct": round(gwetroot * 100, 1) if gwetroot not in (None, -999) else None,
            "surface_moisture_pct": round(gwettop * 100, 1) if gwettop not in (None, -999) else None,
            "daily_rainfall_mm": rainfall if rainfall not in (None, -999) else None,
        }

        print(f"\n🛰️  NASA POWER Data ({result['date']}):")
        print(f"   Root Zone Soil Moisture : {result['root_zone_moisture_pct']}%")
        print(f"   Surface Soil Moisture   : {result['surface_moisture_pct']}%")
        print(f"   Daily Rainfall          : {result['daily_rainfall_mm']} mm")

        return result

    except requests.exceptions.RequestException as e:
        print(f"❌ NASA POWER API Error: {e}")
        return None
    except (KeyError, TypeError) as e:
        print(f"❌ NASA POWER parse error: {e}")
        return None


def get_openmeteo_soil(lat, lon):
    """
    Fetches current hourly soil moisture from Open-Meteo.
    Fast, live, updates hourly. Less accurate than satellite but real-time.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,precipitation"
        f"&hourly=soil_moisture_0_to_1cm"
        f"&forecast_days=1"
        f"&timezone=Asia%2FKolkata"
    )

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        current = data.get("current", {})
        hourly = data.get("hourly", {})

        temp = current.get("temperature_2m", 0)
        humidity = current.get("relative_humidity_2m", 0)
        rainfall = current.get("precipitation", 0.0)

        current_hour = datetime.datetime.now().hour
        soil_array = hourly.get("soil_moisture_0_to_1cm", [])
        raw_soil = soil_array[current_hour] if len(soil_array) > current_hour else None
        if raw_soil is None:
            raw_soil = 0.0

        surface_moisture_pct = round(raw_soil * 100, 1)

        result = {
            "source": "Open-Meteo (GFS Model, Hourly)",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "temperature_c": temp,
            "humidity_pct": humidity,
            "current_rainfall_mm": rainfall,
            "surface_moisture_pct": surface_moisture_pct,
        }

        print(f"\n🌤️  Open-Meteo Data (Live):")
        print(f"   Temperature   : {temp}°C")
        print(f"   Humidity      : {humidity}%")
        print(f"   Rainfall      : {rainfall} mm")
        print(f"   Surface Soil  : {surface_moisture_pct}%")

        return result

    except requests.exceptions.RequestException as e:
        print(f"❌ Open-Meteo Error: {e}")
        return None


def get_blended_soil_report(lat, lon):
    """
    Blends NASA POWER (accurate, 2-day lag) + Open-Meteo (live, less accurate).

    Logic:
    - Use NASA POWER root zone moisture as the 'ground truth' baseline
    - Use Open-Meteo surface moisture for the real-time surface reading
    - Flag if Open-Meteo and NASA diverge too much (possible rainfall event)
    """
    print(f"\n{'='*50}")
    print(f"📍 Soil Moisture Report for ({lat}, {lon})")
    print(f"{'='*50}")

    nasa = get_nasa_power_soil(lat, lon)
    meteo = get_openmeteo_soil(lat, lon)

    print(f"\n{'─'*50}")
    print(f"📊 BLENDED ANALYSIS")
    print(f"{'─'*50}")

    if nasa and meteo:
        nasa_surface = nasa.get("surface_moisture_pct")
        meteo_surface = meteo.get("surface_moisture_pct")
        nasa_root = nasa.get("root_zone_moisture_pct")

        # Check divergence — if Open-Meteo surface is significantly higher than
        # NASA's last reading, it likely rained recently (within the 2-day lag window)
        divergence = None
        if nasa_surface and meteo_surface:
            divergence = round(meteo_surface - nasa_surface, 1)

        print(f"\n   NASA Root Zone Moisture  : {nasa_root}%  (deep, accurate)")
        print(f"   NASA Surface Moisture    : {nasa_surface}%  (2-day old baseline)")
        print(f"   Live Surface Moisture    : {meteo_surface}%  (current estimate)")

        if divergence is not None:
            if divergence > 10:
                print(f"\n   ⚠️  Live reading is {divergence}% HIGHER than NASA baseline.")
                print(f"       Possible recent rainfall event — surface is wetter than usual.")
            elif divergence < -10:
                print(f"\n   ⚠️  Live reading is {abs(divergence)}% LOWER than NASA baseline.")
                print(f"       Possible dry spell — surface may be drying out faster than expected.")
            else:
                print(f"\n   ✅ Live and satellite readings are consistent (divergence: {divergence}%).")

        # Final recommendation for farming
        if nasa_root is not None:
            if nasa_root < 20:
                print(f"\n   🌱 ROOT ZONE STATUS: DRY — Irrigation likely needed.")
            elif nasa_root < 40:
                print(f"\n   🌱 ROOT ZONE STATUS: MODERATE — Monitor closely.")
            elif nasa_root < 70:
                print(f"\n   🌱 ROOT ZONE STATUS: GOOD — Adequate moisture for most crops.")
            else:
                print(f"\n   🌱 ROOT ZONE STATUS: SATURATED — Risk of waterlogging.")

    elif nasa:
        print("   (Open-Meteo unavailable — NASA data only)")
        print(f"   Root Zone: {nasa.get('root_zone_moisture_pct')}%")
    elif meteo:
        print("   (NASA unavailable — Open-Meteo data only)")
        print(f"   Surface: {meteo.get('surface_moisture_pct')}%")
    else:
        print("   ❌ Both sources failed. Check network connection.")

    print(f"\n{'='*50}\n")

    return {"nasa": nasa, "open_meteo": meteo}


# --- Run directly ---
if __name__ == "__main__":
    LAT = 30.107108
    LON = 77.098991
    get_blended_soil_report(LAT, LON)