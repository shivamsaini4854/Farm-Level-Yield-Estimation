"""Shared monthly satellite processing for 1 km point buffers, never field labels."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
import os
import time

from dotenv import load_dotenv
import ee
import pandas as pd

from farm_yield.acquisition.live import ObservationsUnavailable
from farm_yield.paths import ENV_FILE, GEO_DATA, RAW_DATA
from farm_yield.seasons import season_months


PROCESSING_VERSION = 'point-buffer-v1'
SOURCES = {
    'vegetation': ('MODIS/061/MOD13Q1', ['ndvi', 'evi'], 250),
    'temperature': ('MODIS/061/MOD11A2', ['lst_day_c'], 1000),
    'red_edge': ('COPERNICUS/S2_HARMONIZED', ['ndre'], 20),
}


def initialize():
    load_dotenv(ENV_FILE)
    options = {}
    if os.getenv('GEE_REFRESH_TOKEN'):
        from google.oauth2.credentials import Credentials
        options['credentials'] = Credentials(None, refresh_token=os.environ['GEE_REFRESH_TOKEN'],
            token_uri=ee.oauth.TOKEN_URI, client_id=ee.oauth.CLIENT_ID, client_secret=ee.oauth.CLIENT_SECRET)
    ee.Initialize(project=os.getenv('GEE_PROJECT') or None, **options)
    ee.data.setDeadline(120000)


def vegetation(image):
    values = image.select(['NDVI', 'EVI']).multiply(0.0001).rename(['ndvi', 'evi'])
    mask = image.select('SummaryQA').lte(1).And(values.gte(-1).And(values.lte(1)).reduce(ee.Reducer.min()))
    return values.updateMask(mask)


def temperature(image):
    quality = image.select('QC_Day')
    mask = quality.bitwiseAnd(3).eq(0).And(quality.rightShift(6).bitwiseAnd(3).eq(0))
    return image.select('LST_Day_1km').multiply(0.02).subtract(273.15).rename('lst_day_c').updateMask(mask)


def red_edge(image):
    a, b = image.select('B8A'), image.select('B5')
    denominator = a.add(b)
    mask = image.select('cs_cdf').gte(0.60).And(denominator.gt(0)).And(a.gt(0)).And(b.gt(0))
    return a.subtract(b).divide(denominator).rename('ndre').updateMask(mask)


def monthly_collection(kind, start, end, bounds):
    source = ee.ImageCollection(SOURCES[kind][0]).filterDate(start, end).filterBounds(bounds)
    if kind == 'vegetation':
        return source.map(vegetation)
    if kind == 'temperature':
        return source.map(temperature)
    scores = ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
    return source.linkCollection(scores, ['cs_cdf']).map(red_edge)


def extract_source(kind, locations, month):
    start = ee.Date(month)
    end = start.advance(1, 'month')
    areas = ee.FeatureCollection([ee.Feature(ee.Geometry.Point([r['lon'], r['lat']]).buffer(1000),
        {'location_id': r['location_id']}) for r in locations])
    collection = monthly_collection(kind, start, end, areas.geometry())
    _, bands, scale = SOURCES[kind]
    empty = ee.Image.constant([0] * len(bands)).rename(bands).updateMask(ee.Image.constant(0))
    collection = collection.merge(ee.ImageCollection([empty]))
    composite = collection.mean().addBands(collection.count().rename([b + '_observations' for b in bands]))
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
    result = composite.reduceRegions(collection=areas, reducer=reducer, scale=scale,
                                     crs='EPSG:4326', tileScale=4).getInfo()
    rows = {}
    for feature in result['features']:
        properties = feature['properties']
        row = {}
        for band in bands:
            row[band] = properties.get(band + '_mean')
            row[band + '_pixels'] = properties.get(band + '_count', 0)
            row[band + '_observations'] = properties.get(band + '_observations_mean', 0)
        rows[properties['location_id']] = row
    if set(rows) != {r['location_id'] for r in locations}:
        raise ObservationsUnavailable('Satellite batch did not return each requested location.')
    return rows


def extract_month(locations, month):
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda kind: extract_source(kind, locations, month), SOURCES))
    return [{'location_id': r['location_id'], 'month': month,
             **{key: value for result in results for key, value in result[r['location_id']].items()}}
            for r in locations]


def fetch_point_season(lat, lon, start, end):
    try:
        initialize()
        location = [{'lat': lat, 'lon': lon, 'location_id': 'requested'}]
        return {month.isoformat(): extract_month(location, month.isoformat())[0]
                for month in season_months(start, end)}
    except (ee.EEException, OSError, ValueError) as exc:
        raise ObservationsUnavailable('Satellite observations could not be retrieved.') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', action='store_true', help='Probe three locations for January 2016 only.')
    parser.add_argument('--verified-sample', action='store_true', help='Require recorded quality approval before national acquisition.')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2, help='Concurrent month batches; at most six source requests.')
    args = parser.parse_args()
    cache = RAW_DATA / 'satellite' / PROCESSING_VERSION
    cache.mkdir(parents=True, exist_ok=True)
    if not args.sample and not (args.verified_sample and (cache / 'sample_verification.json').exists()):
        parser.error('Review the small sample and save sample_verification.json before national acquisition.')
    locations = pd.read_csv(GEO_DATA / 'district_locations.csv').to_dict('records')
    for row in locations:
        row['location_id'] = row['shape_id']
    if args.sample:
        locations = locations[:3]
        months = [date(2016, 1, 1)]
    else:
        months = list(season_months(date(2015, 7, 1), date(2019, 12, 31)))
    initialize()
    started = time.monotonic()
    def acquire(month):
        target = cache / (('sample-' if args.sample else '') + month.isoformat() + '.json')
        if target.exists():
            saved = json.loads(target.read_text(encoding='utf-8'))
            if {r['location_id'] for r in saved['records']} != {r['location_id'] for r in locations}:
                raise ValueError('Cached satellite locations differ; use a new processing version.')
            return 'skipped', None
        try:
            records = extract_month(locations, month.isoformat())
            document = {'processing_version': PROCESSING_VERSION, 'sources': SOURCES,
                        'buffer_m': 1000, 'analysis_crs': 'EPSG:4326', 'records': records}
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(document, allow_nan=False), encoding='utf-8')
            temporary.replace(target)
            print(f'PASS: {month}: {len(records)} locations', flush=True)
            return 'success', None
        except (ee.EEException, OSError, ValueError) as exc:
            print(f'FAIL: {month}: {type(exc).__name__}: {exc}', flush=True)
            return 'failed', {'month': month.isoformat(), 'error': str(exc)}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(acquire, months))
    success = sum(status == 'success' for status, _ in results)
    skipped = sum(status == 'skipped' for status, _ in results)
    failed = [error for status, error in results if status == 'failed']
    manifest = {'success': success, 'failed': failed, 'skipped': skipped,
                'expected_months': len(months), 'locations': len(locations), 'sources': SOURCES,
                'elapsed_seconds': time.monotonic() - started, 'workers': args.workers}
    (cache / ('sample_manifest.json' if args.sample else 'manifest.json')).write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
