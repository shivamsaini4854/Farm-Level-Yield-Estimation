"""Completed-season point observations, with explicit missing-data failures."""

import pandas as pd
import requests

from farm_yield.features import WEATHER_COLUMNS


NASA_PARAMETERS = ('T2M', 'T2M_MAX', 'T2M_MIN', 'PRECTOTCORR', 'RH2M',
                   'WS2M', 'ALLSKY_SFC_SW_DWN', 'GWETROOT', 'GWETTOP')


class ObservationsUnavailable(RuntimeError):
    pass


def aggregate_weather(daily, start, end):
    frame = daily.copy()
    frame.index = pd.to_datetime(frame.index)
    frame = frame.loc[str(start):str(end), list(NASA_PARAMETERS)].sort_index()
    expected = pd.date_range(start, end, freq='D')
    if frame.index.has_duplicates or not frame.index.equals(expected):
        raise ObservationsUnavailable('Weather does not cover every day of the completed season.')
    frame = frame.apply(pd.to_numeric, errors='coerce').replace([-999, float('inf'), -float('inf')], float('nan'))
    if frame.isna().any().any():
        raise ObservationsUnavailable('Weather has missing or invalid daily measurements.')
    records = []
    for period, group in frame.groupby(frame.index.to_period('M')):
        row = {'month': period.start_time.date().isoformat(), 'days': len(group)}
        for parameter, column in zip(NASA_PARAMETERS, WEATHER_COLUMNS):
            row[column] = float(group[parameter].sum() if parameter in ('PRECTOTCORR', 'ALLSKY_SFC_SW_DWN') else group[parameter].mean())
        records.append(row)
    return records


def fetch_weather(lat, lon, start, end):
    try:
        response = requests.get('https://power.larc.nasa.gov/api/temporal/daily/point', params={
            'parameters': ','.join(NASA_PARAMETERS), 'community': 'AG',
            'latitude': lat, 'longitude': lon, 'start': start.strftime('%Y%m%d'),
            'end': end.strftime('%Y%m%d'), 'format': 'JSON',
        }, timeout=30)
        response.raise_for_status()
        parameters = response.json()['properties']['parameter']
        daily = pd.DataFrame(parameters)
        daily.index = pd.to_datetime(daily.index, format='%Y%m%d')
        return aggregate_weather(daily, start, end)
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        raise ObservationsUnavailable('NASA POWER observations could not be retrieved.') from exc
