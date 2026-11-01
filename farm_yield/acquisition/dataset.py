"""Audit APY labels and join only geographically checked, complete observations."""

import argparse
import hashlib
import json
import re
import unicodedata

import numpy as np
import pandas as pd

from farm_yield.acquisition.fetch_nasa_power import DISTRICT_COORDS
from farm_yield.acquisition.live import ObservationsUnavailable, aggregate_weather
from farm_yield.paths import GEO_DATA, PROCESSED_DATA, RAW_DATA
from farm_yield.seasons import CROPS, CROP_SEASONS, label_harvest_year, season_dates


KEYS = ['State', 'District', 'Crop', 'Season', 'harvest_year']


def normalized(value):
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().upper()
    return re.sub('[^A-Z0-9]', '', value)


STATE_ALIASES = {'ORISSA': 'ODISHA', 'UTTARANCHAL': 'UTTARAKHAND',
                 'PONDICHERRY': 'PUDUCHERRY', 'NCTOFDELHI': 'DELHI',
                 'ANDAMANANDNICOBARISLAND': 'ANDAMANNICOBAR',
                 'ANDAMANNICOBARISLANDS': 'ANDAMANNICOBAR',
                 'JAMMUANDKASHMIR': 'JAMMUKASHMIR', 'JAMMUKASHMIR': 'JAMMUKASHMIR'}


def state_key(value):
    key = normalized(value)
    return STATE_ALIASES.get(key, key)


def clean_labels(frame):
    frame = frame.rename(columns=lambda value: value.strip()).copy()
    for column in ('State', 'District', 'Crop', 'Season'):
        frame[column] = frame[column].str.strip()
    frame = frame[frame.Crop.isin(CROPS)].copy()
    frame['harvest_year'] = [label_harvest_year(y, s) for y, s in zip(frame.Crop_Year, frame.Season)]
    frame = frame[frame.harvest_year.between(2016, 2019)].copy()
    frame['reason'] = ''
    frame.loc[frame.Season != frame.Crop.map(CROP_SEASONS), 'reason'] = 'unsupported_crop_season'
    invalid = ~np.isfinite(frame[['Area', 'Production', 'Yield']]).all(axis=1) | (frame.Area <= 0) | (frame.Production < 0) | (frame.Yield < 0)
    frame.loc[invalid, 'reason'] = 'invalid_target_or_area'
    inconsistent = (frame.Production / frame.Area - frame.Yield).abs() > 0.015
    frame.loc[inconsistent & ~invalid, 'reason'] = 'yield_not_production_per_area'
    # Chhattisgarh's APY totals disagree with the checked cane source; no unit conversion is justified.
    frame.loc[(frame.Crop == 'Sugarcane') & (frame.State == 'Chhattisgarh'), 'reason'] = 'sugarcane_source_definition_unresolved'
    duplicates = frame.duplicated(KEYS, keep=False)
    conflicts = frame.groupby(KEYS)[['Area', 'Production', 'Yield']].transform('nunique').gt(1).any(axis=1)
    frame.loc[duplicates & conflicts, 'reason'] = 'conflicting_duplicate'
    quarantine = frame[frame.reason != ''].copy()
    accepted = frame[frame.reason == ''].drop_duplicates(KEYS).drop(columns='reason')
    assert not accepted.duplicated(KEYS).any()
    return accepted, quarantine, len(frame) - len(accepted) - len(quarantine)


def geography(pairs):
    from shapely.geometry import Point, shape
    states = [(state_key(f['properties']['shapeName']), shape(f['geometry']))
              for f in json.loads((GEO_DATA / 'adm1.geojson').read_text(encoding='utf-8'))['features']]
    districts = {}
    for f in json.loads((GEO_DATA / 'adm2.geojson').read_text(encoding='utf-8'))['features']:
        polygon = shape(f['geometry'])
        point = polygon.representative_point()
        owners = [name for name, area in states if area.covers(point)]
        if len(owners) == 1:
            key = (owners[0], normalized(f['properties']['shapeName']))
            districts.setdefault(key, []).append((f['properties']['shapeID'], polygon))
    accepted, rejected = [], []
    for state, district in pairs:
        matches = districts.get((state_key(state), normalized(district)), [])
        coords = DISTRICT_COORDS.get(district)
        reason = None
        if len(matches) != 1:
            reason = 'unresolved_boundary_name'
        elif coords is None or not (RAW_DATA / 'nasa_power' / (district + '.csv')).exists():
            reason = 'weather_cache_or_coordinates_missing'
        elif not matches[0][1].covers(Point(coords[1], coords[0])):
            reason = 'weather_point_outside_district'
        if reason:
            rejected.append({'State': state, 'District': district, 'reason': reason})
        else:
            accepted.append({'State': state, 'District': district, 'shape_id': matches[0][0],
                             'lat': coords[0], 'lon': coords[1]})
    return pd.DataFrame(accepted), pd.DataFrame(rejected)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    PROCESSED_DATA.mkdir(exist_ok=True, parents=True)
    labels, quarantine, duplicates = clean_labels(pd.read_csv(RAW_DATA / 'APY.csv'))
    locations, unmatched = geography(labels[['State', 'District']].drop_duplicates().itertuples(index=False, name=None))
    locations.to_csv(GEO_DATA / 'district_locations.csv', index=False)
    labels = labels.merge(locations, on=['State', 'District'], validate='many_to_one')
    accepted, failed, monthly = [], [], []
    for (state, district), group in labels.groupby(['State', 'District']):
        daily = pd.read_csv(RAW_DATA / 'nasa_power' / (district + '.csv'), index_col='date', parse_dates=True)
        daily = daily.loc['2015-07-01':'2019-12-31']
        seasons = {}
        for row in group.to_dict('records'):
            start, end = season_dates(row['Season'], row['harvest_year'])
            try:
                key = (start, end)
                if key not in seasons:
                    seasons[key] = aggregate_weather(daily, start, end)
                records = seasons[key]
            except ObservationsUnavailable as exc:
                failed.append({**row, 'reason': str(exc)})
                continue
            row.update(start=start.isoformat(), end=end.isoformat())
            accepted.append(row)
            monthly.extend({'State': state, 'District': district, **record} for record in records)
        print(f'Checked {state}/{district}: {len(group)} labels', flush=True)
    labels = pd.DataFrame(accepted)
    weather = pd.DataFrame(monthly).drop_duplicates(['State', 'District', 'month'])
    assert not labels.duplicated(KEYS).any()
    labels.to_csv(PROCESSED_DATA / 'labels.csv', index=False)
    weather.to_csv(PROCESSED_DATA / 'monthly_weather.csv', index=False)
    quarantine.to_csv(PROCESSED_DATA / 'quarantine_labels.csv', index=False)
    unmatched.to_csv(PROCESSED_DATA / 'quarantine_geography.csv', index=False)
    pd.DataFrame(failed).to_csv(PROCESSED_DATA / 'quarantine_weather.csv', index=False)
    locations.to_csv(GEO_DATA / 'district_locations.csv', index=False)
    counts = labels.groupby(['Crop', 'harvest_year']).size().unstack(fill_value=0)
    counts.to_csv(PROCESSED_DATA / 'label_coverage.csv')
    with (RAW_DATA / 'APY.csv').open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    report = {'apy_sha256': digest, 'accepted_labels': len(labels), 'weather_months': len(weather),
              'quarantined_labels': len(quarantine), 'exact_duplicates_removed': duplicates,
              'unresolved_geographic_pairs': len(unmatched), 'incomplete_weather_labels': len(failed),
              'accepted_districts': len(locations), 'crops': sorted(labels.Crop.unique().tolist()),
              'year_semantics': 'APY agricultural starting year; Rabi/Whole Year end in following year',
              'whole_year_window': 'July through June reporting year; planting dates unobserved'}
    (PROCESSED_DATA / 'dataset_audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
