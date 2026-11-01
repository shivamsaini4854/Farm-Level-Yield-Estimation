from datetime import date
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import requests

from farm_yield.acquisition.dataset import clean_labels
from farm_yield.acquisition.live import NASA_PARAMETERS, ObservationsUnavailable, aggregate_weather, fetch_weather
from farm_yield.features import MONTHLY_COLUMNS, build_feature_row, feature_columns, validate_monthly_record
from farm_yield.seasons import label_harvest_year, season_dates


class FeatureTests(unittest.TestCase):
    def test_starting_year_and_reporting_year_windows(self):
        self.assertEqual(label_harvest_year(2015, 'Rabi'), 2016)
        self.assertEqual(label_harvest_year(2016, 'Kharif'), 2016)
        self.assertEqual(season_dates('Whole Year', 2016), (date(2015, 7, 1), date(2016, 6, 30)))

    def test_complete_cross_year_weather_and_missing_day_failure(self):
        start, end = season_dates('Rabi', 2016)
        daily = pd.DataFrame(1.0, index=pd.date_range(start, end), columns=NASA_PARAMETERS)
        rows = aggregate_weather(daily, start, end)
        self.assertEqual([r['days'] for r in rows], [31, 30, 31, 31, 29, 31])
        self.assertEqual(sum(r['rainfall_mm'] for r in rows), 183)
        with self.assertRaises(ObservationsUnavailable):
            aggregate_weather(daily.drop(daily.index[0]), start, end)
        daily.iloc[0, 0] = -999
        with self.assertRaises(ObservationsUnavailable):
            aggregate_weather(daily, start, end)

    def test_conflicting_keys_are_quarantined_and_exact_duplicates_removed(self):
        row = {'State': 'Punjab', 'District': 'LUDHIANA', 'Crop': 'Wheat', 'Season': 'Rabi',
               'Crop_Year': 2015, 'Area': 100, 'Production': 400, 'Yield': 4.0}
        accepted, rejected, duplicates = clean_labels(pd.DataFrame([row, row]))
        self.assertEqual((len(accepted), len(rejected), duplicates), (1, 0, 1))
        accepted, rejected, _ = clean_labels(pd.DataFrame([row, {**row, 'Production': 500, 'Yield': 5.0}]))
        self.assertEqual(len(accepted), 0)
        self.assertEqual(rejected.reason.tolist(), ['conflicting_duplicate', 'conflicting_duplicate'])

    def test_schema_order_missingness_and_duplicate_month(self):
        start, end = date(2015, 10, 1), date(2016, 3, 31)
        rows = [{'month': month, **{c: 1.0 for c in MONTHLY_COLUMNS}} for month in
                ('2015-10-01', '2015-11-01', '2015-12-01', '2016-01-01', '2016-02-01', '2016-03-01')]
        rows[0]['ndre'] = None
        frame = build_feature_row(rows, 'Wheat', start, end)
        self.assertEqual(frame.columns.tolist(), feature_columns())
        self.assertEqual(len(set(frame.columns)), len(frame.columns))
        self.assertTrue(np.isnan(frame.at[0, 'm01_ndre']))
        self.assertEqual(frame.at[0, 'm01_ndre_available'], 0)
        self.assertEqual(frame.at[0, 'm07_in_season'], 0)
        with self.assertRaises(ValueError):
            build_feature_row(rows + rows[:1], 'Wheat', start, end)

    def test_upstream_error_is_exposed_and_invalid_calendar_record_rejected(self):
        with patch('farm_yield.acquisition.live.requests.get', side_effect=requests.ConnectionError('forced outage')):
            with self.assertRaises(ObservationsUnavailable):
                fetch_weather(30, 77, date(2016, 1, 1), date(2016, 1, 31))
        record = {'State': 'Punjab', 'District': 'LUDHIANA', 'month': '2016-02-01', 'days': 31,
                  **{column: .4 for column in MONTHLY_COLUMNS}}
        with self.assertRaisesRegex(ValueError, 'calendar month'):
            validate_monthly_record(record)

    def test_verified_punjab_cane_is_retained_and_unresolved_cg_is_quarantined(self):
        row = {'State': 'Punjab', 'District': 'LUDHIANA', 'Crop': 'Sugarcane', 'Season': 'Whole Year',
               'Crop_Year': 2015, 'Area': 90000., 'Production': 6607000., 'Yield': 73.41}
        accepted, rejected, _ = clean_labels(pd.DataFrame([row, {**row, 'State': 'Chhattisgarh'}]))
        self.assertEqual(accepted.State.tolist(), ['Punjab'])
        self.assertEqual(rejected.reason.tolist(), ['sugarcane_source_definition_unresolved'])
