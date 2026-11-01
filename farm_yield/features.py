"""Monthly feature contract used by acquisition, training, and prediction."""

from datetime import date
import calendar
import math

import numpy as np
import pandas as pd

from farm_yield.seasons import CROPS, CROP_SEASONS, season_months


WEATHER_COLUMNS = (
    'temp_mean_c', 'temp_max_c', 'temp_min_c', 'rainfall_mm', 'humidity_pct',
    'wind_speed_ms', 'solar_radiation_mj', 'soil_moisture_root', 'soil_moisture_surface',
)
SATELLITE_COLUMNS = ('ndvi', 'evi', 'lst_day_c', 'ndre')
MONTHLY_COLUMNS = WEATHER_COLUMNS + SATELLITE_COLUMNS
SEASONS = ('Kharif', 'Rabi', 'Whole Year')


def feature_columns(columns=MONTHLY_COLUMNS):
    names = []
    for month in range(1, 13):
        names.extend(f'm{month:02d}_{column}' for column in columns)
        names.extend(f'm{month:02d}_{column}_available' for column in columns)
        names.append(f'm{month:02d}_in_season')
    return names + [f'crop_{crop}' for crop in CROPS] + [f'season_{season}' for season in SEASONS]


def validate_monthly_record(record):
    if not isinstance(record, dict):
        raise ValueError('Each observation must be an object.')
    allowed = {'State', 'District', 'month', 'days'} | set(MONTHLY_COLUMNS)
    if set(record) - allowed:
        raise ValueError('Observation contains unsupported fields.')
    for key in ('State', 'District'):
        if not isinstance(record.get(key), str) or not 1 <= len(record[key].strip()) <= 120:
            raise ValueError(f'{key} must be a nonempty name of at most 120 characters.')
    try:
        month = date.fromisoformat(record['month'])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError('month must be an ISO date on the first day of a month.') from exc
    if month.day != 1:
        raise ValueError('month must be the first day of a month.')
    days = record.get('days')
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= calendar.monthrange(month.year, month.month)[1]:
        raise ValueError('days must fit the observation calendar month.')
    for column in MONTHLY_COLUMNS:
        value = record.get(column)
        if value is None and column in SATELLITE_COLUMNS:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{column} must be finite; unavailable satellite values must be null.')
        if column in ('ndvi', 'evi', 'ndre') and not -1 <= value <= 1:
            raise ValueError(f'{column} is outside [-1, 1].')
        if column.startswith('soil_moisture') and not 0 <= value <= 1:
            raise ValueError(f'{column} is outside [0, 1].')
        if column == 'humidity_pct' and not 0 <= value <= 100:
            raise ValueError('humidity_pct is outside [0, 100].')
        if column in ('rainfall_mm', 'solar_radiation_mj', 'wind_speed_ms') and value < 0:
            raise ValueError(f'{column} must be nonnegative.')
    return record


def build_feature_row(records, crop, start, end, columns=MONTHLY_COLUMNS):
    if crop not in CROPS:
        raise ValueError('Unsupported crop.')
    expected = [month.isoformat() for month in season_months(start, end)]
    by_month = {record['month']: record for record in records}
    if len(by_month) != len(records) or set(by_month) != set(expected):
        raise ValueError('Observations must contain each season month exactly once.')
    row = {}
    for index in range(1, 13):
        record = by_month[expected[index - 1]] if index <= len(expected) else {}
        for column in columns:
            value = record.get(column)
            observed = value is not None and pd.notna(value)
            if observed and not math.isfinite(float(value)):
                raise ValueError('Features must not contain infinity.')
            row[f'm{index:02d}_{column}'] = float(value) if observed else np.nan
            row[f'm{index:02d}_{column}_available'] = int(observed)
        row[f'm{index:02d}_in_season'] = int(bool(record))
    row.update({f'crop_{name}': int(crop == name) for name in CROPS})
    row.update({f'season_{name}': int(CROP_SEASONS[crop] == name) for name in SEASONS})
    return pd.DataFrame([row], columns=feature_columns(columns))


def weather_summary(records):
    days = sum(record['days'] for record in records)
    return {
        'temp': round(sum(r['temp_mean_c'] * r['days'] for r in records) / days, 1),
        'rainfall': round(sum(r['rainfall_mm'] for r in records), 1),
        'humidity': round(sum(r['humidity_pct'] * r['days'] for r in records) / days, 1),
        'soil': round(100 * sum(r['soil_moisture_root'] * r['days'] for r in records) / days, 1),
        'days': days,
    }
