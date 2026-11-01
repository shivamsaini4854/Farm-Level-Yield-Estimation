from datetime import date
import hashlib
import json
import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline

from farm_yield import database
from farm_yield.features import MONTHLY_COLUMNS, build_feature_row
from farm_yield.ml.train import preprocessing
from farm_yield.ml import artifacts
from farm_yield.seasons import CROPS, completed_season, season_months
from farm_yield.web import create_app


class ServingTests(unittest.TestCase):
    def setUp(self):
        start, end, _, _ = completed_season('Wheat', date(2026, 10, 22), [2016, 2017, 2018, 2019])
        self.assertEqual((start, end), (date(2018, 10, 1), date(2019, 3, 31)))
        self.records = [{'month': m.isoformat(), 'days': 30, **{name: .4 for name in MONTHLY_COLUMNS}}
                        for m in season_months(start, end)]
        frame = build_feature_row(self.records, 'Wheat', start, end)
        pipeline = DummyRegressor(strategy='constant', constant=2).fit(frame, [2])
        bundle = {'pipeline': pipeline, 'metadata': {'harvest_years': [2016, 2017, 2018, 2019],
                  'monthly_columns': list(MONTHLY_COLUMNS), 'feature_columns': frame.columns.tolist(),
                  'target_scales': {crop: 5 for crop in CROPS}, 'model_name': 'Test',
                  'run_id': 'fixture', 'evidence_limits': ['District evidence only.']},
                  'observations': {'district-one': {r['month']: r for r in self.records}}}
        self.bundle = bundle
        with patch('farm_yield.web.load_current', return_value=bundle):
            self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-' + 'session',
                                   'SESSION_KEY_CONFIGURED': True, 'ADMIN_API_KEY': 'admin-' + 'fixture'})
        self.client = self.app.test_client()

    def test_success_returns_versioned_prediction_and_saves_own_session(self):
        with patch('farm_yield.web.resolve_district', return_value={'shape_id': 'district-one', 'district': 'Example'}), \
             patch('farm_yield.web.database.save_prediction') as save:
            result = self.client.post('/api/fetch_ndvi', json={'lat': 30, 'lon': 77, 'crop': 'Wheat'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['prediction'], 10)
        self.assertEqual(result.json['harvest_year'], 2019)
        self.assertEqual(result.json['analysis_mode'], 'historical_replay')
        self.assertEqual(result.json['feature_availability']['ndre'], 6)
        self.assertEqual(save.call_args.args[1]['prediction_id'], result.json['prediction_id'])
        with self.client.session_transaction() as session:
            self.assertEqual(save.call_args.args[0], session['visitor_id'])

    def test_incomplete_observations_and_storage_failure_are_distinct(self):
        with patch('farm_yield.web.resolve_district', return_value={'shape_id': 'missing', 'district': 'Example'}):
            response = self.client.post('/api/fetch_ndvi', json={'lat': 30, 'lon': 77, 'crop': 'Wheat'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json['status'], 'data_unavailable')
        with patch('farm_yield.web.resolve_district', return_value={'shape_id': 'district-one', 'district': 'Example'}), \
             patch('farm_yield.web.database.save_prediction', side_effect=database.DatabaseUnavailable('Storage failed')):
            response = self.client.post('/api/fetch_ndvi', json={'lat': 30, 'lon': 77, 'crop': 'Wheat'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('prediction', response.json)

    def test_preprocessing_never_learns_validation_values(self):
        train = pd.DataFrame({'value': [1., 3., float('nan')]})
        prep = preprocessing().fit(train)
        self.assertEqual(prep['imputer'].statistics_[0], 2.)
        prep.transform(pd.DataFrame({'value': [99999., float('nan')]}))
        self.assertEqual(prep['imputer'].statistics_[0], 2.)
        self.assertEqual(prep['scaler'].mean_[0], 2.)

    def test_serialized_forest_predictions_are_exactly_repeatable(self):
        frame = pd.DataFrame({'temperature': [12., 18., 25., 28., 31., 36.],
                              'rain': [3., 2., 7., 12., 9., 1.]})
        model = Pipeline([('preprocessing', preprocessing()), ('model', RandomForestRegressor(
            n_estimators=12, random_state=42, n_jobs=1))]).fit(frame, [1.2, 1.8, 2.1, 2.3, 1.9, 1.1])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bundle.pkl'
            joblib.dump(model, path)
            np.testing.assert_array_equal(joblib.load(path).predict(frame), model.predict(frame))

    def test_artifact_hash_and_feature_order_fail_closed(self):
        self.bundle['metadata'].update(schema_version=2, verified=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / 'runs'
            run = runs / 'fixture'
            run.mkdir(parents=True)
            path, current = run / 'bundle.pkl', root / 'current.json'
            def save():
                joblib.dump(self.bundle, path)
                current.write_text(json.dumps({'run_id': 'fixture',
                    'bundle_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}), encoding='utf-8')
            save()
            with patch.object(artifacts, 'CURRENT', current), patch.object(artifacts, 'RUNS', runs):
                self.assertEqual(artifacts.load_current()['metadata']['run_id'], 'fixture')
                with path.open('ab') as stream:
                    stream.write(b'changed')
                with self.assertRaises(artifacts.ModelUnavailable):
                    artifacts.load_current()
                self.bundle['metadata']['feature_columns'].reverse()
                save()
                with self.assertRaises(artifacts.ModelUnavailable):
                    artifacts.load_current()
