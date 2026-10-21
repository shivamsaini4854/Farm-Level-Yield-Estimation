"""Coordinate validation shared by API and ingestion boundaries."""

import math

INDIA_BOUNDS = {
    "min_lat": 6.0,
    "max_lat": 38.5,
    "min_lon": 67.0,
    "max_lon": 98.5,
}

INDIA_MAINLAND_POLYGON = [
    (23.5, 68.0), (24.8, 68.7), (26.6, 69.4), (29.0, 70.2), (31.8, 74.2),
    (34.2, 75.5), (35.8, 77.4), (35.8, 79.8), (34.0, 78.6), (31.8, 78.0),
    (30.1, 79.0), (28.2, 80.6), (27.0, 82.8), (26.1, 84.6), (25.7, 86.8),
    (25.5, 88.5), (24.5, 89.5), (23.0, 89.9), (21.7, 89.5), (20.6, 88.8),
    (21.0, 87.2), (20.7, 86.0), (19.7, 85.0), (19.0, 83.8), (18.3, 82.8),
    (17.3, 81.5), (16.1, 80.5), (15.0, 80.3), (13.5, 80.2), (12.1, 79.8),
    (10.8, 79.2), (9.1, 78.8), (8.1, 77.6), (8.2, 76.2), (9.2, 75.4),
    (10.6, 74.8), (12.2, 74.3), (13.8, 74.0), (15.2, 73.8), (17.0, 73.4),
    (18.6, 72.9), (20.0, 72.2), (21.1, 71.5), (22.0, 70.6), (22.8, 69.6),
    (23.3, 68.8)
]

INDIA_NORTHEAST_POLYGON = [
    (22.0, 88.0), (23.0, 88.6), (24.2, 89.8), (25.4, 90.8), (26.6, 91.8),
    (27.6, 92.8), (28.7, 94.0), (29.4, 95.2), (29.6, 96.6), (29.1, 97.6),
    (28.0, 97.9), (26.8, 97.6), (25.8, 96.9), (24.8, 96.0), (24.0, 95.0),
    (23.4, 94.0), (22.8, 93.0), (22.4, 92.0), (22.1, 90.8), (22.0, 89.2)
]

INDIA_ISLAND_BOXES = [
    {"min_lat": 6.0, "max_lat": 14.5, "min_lon": 92.0, "max_lon": 94.5},
    {"min_lat": 8.0, "max_lat": 13.8, "min_lon": 72.0, "max_lon": 74.0},
]

def normalize_longitude(lon):
    return ((lon + 180.0) % 360.0) - 180.0

def point_in_polygon(lat, lon, polygon):
    inside = False
    j = len(polygon) - 1

    for i in range(len(polygon)):
        yi, xi = polygon[i]
        yj, xj = polygon[j]

        intersects = ((xi > lon) != (xj > lon)) and (
            lat < (yj - yi) * (lon - xi) / ((xj - xi) or 1e-12) + yi
        )
        if intersects:
            inside = not inside
        j = i

    return inside

def is_within_india(lat, lon):
    if point_in_polygon(lat, lon, INDIA_MAINLAND_POLYGON):
        return True
    if point_in_polygon(lat, lon, INDIA_NORTHEAST_POLYGON):
        return True

    for box in INDIA_ISLAND_BOXES:
        if (
            box["min_lat"] <= lat <= box["max_lat"] and
            box["min_lon"] <= lon <= box["max_lon"]
        ):
            return True

    return False

def normalize_and_validate_coordinates(lat, lon, restrict_to_india=False):
    if isinstance(lat, bool) or isinstance(lon, bool):
        raise ValueError("Coordinates must be numbers.")
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError) as exc:
        raise ValueError("Coordinates must be numbers.") from exc
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("Coordinates must be finite.")
    lon = normalize_longitude(lon)

    if not (-90.0 <= lat <= 90.0):
        raise ValueError("Latitude must be between -90 and 90.")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("Longitude must be between -180 and 180.")

    if restrict_to_india:
        if not (
            INDIA_BOUNDS["min_lat"] <= lat <= INDIA_BOUNDS["max_lat"] and
            INDIA_BOUNDS["min_lon"] <= lon <= INDIA_BOUNDS["max_lon"] and
            is_within_india(lat, lon)
        ):
            raise ValueError("Please select a location in India.")

    return lat, lon
