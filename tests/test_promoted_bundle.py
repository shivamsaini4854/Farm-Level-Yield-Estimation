"""Check the public serving transformation against saved backtest evidence."""
import json
import unittest
from unittest.mock import patch

import pandas as pd

from farm_yield.paths import CURRENT, PROCESSED_DATA, RUNS
from farm_yield.web import create_app


class PromotedBundleTests(unittest.TestCase):
    def test_all_16_crops_match_saved_backtest_predictions_through_the_api(self):
        manifest = json.loads(CURRENT.read_text(encoding='utf-8'))
        directory = RUNS / manifest['run_id']
        metadata = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
        predictions = pd.read_csv(directory / 'predictions.csv')
        labels = pd.read_csv(PROCESSED_DATA / 'labels.csv')
        rows = predictions[predictions.harvest_year == 2019].groupby('Crop', sort=False).head(1)
        rows = rows.merge(labels[['State', 'District', 'Crop', 'harvest_year', 'lat', 'lon']],
                          on=['State', 'District', 'Crop', 'harvest_year'], validate='one_to_one')
        self.assertEqual(len(rows), 16)
        application = create_app({'TESTING': True})
        client = application.test_client()
        with patch('farm_yield.web.database.save_prediction') as save:
            for row in rows.to_dict('records'):
                with self.subTest(crop=row['Crop']):
                    response = client.post('/api/fetch_ndvi', json={
                        'lat': row['lat'], 'lon': row['lon'], 'crop': row['Crop']})
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assertEqual(response.json['model_version'], manifest['run_id'])
                    self.assertEqual(response.json['prediction'], round(row[metadata['model_name']], 2))
            self.assertEqual(save.call_count, 16)
