"""Resolve pins against the same contemporary district boundaries used in the audit."""

from functools import lru_cache
import json

from farm_yield.coordinates import point_in_polygon
from farm_yield.paths import GEO_DATA


@lru_cache(maxsize=1)
def districts():
    collection = json.loads((GEO_DATA / 'coverage.geojson').read_text(encoding='utf-8'))
    areas = []
    for feature in collection['features']:
        geometry = feature['geometry']
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        for polygon in polygons:
            rings = [[(lat, lon) for lon, lat in ring] for ring in polygon]
            lats, lons = zip(*rings[0])
            areas.append((feature['properties'], rings, (min(lats), max(lats), min(lons), max(lons))))
    return areas


def resolve_district(lat, lon):
    matches = {}
    for properties, rings, (south, north, west, east) in districts():
        if south <= lat <= north and west <= lon <= east:
            if point_in_polygon(lat, lon, rings[0]) and not any(point_in_polygon(lat, lon, ring) for ring in rings[1:]):
                matches[properties['shape_id']] = properties
    if len(matches) != 1:
        raise ValueError('Location does not resolve to one supported district boundary.')
    return next(iter(matches.values()))
