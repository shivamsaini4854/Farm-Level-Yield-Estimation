from datetime import date
import json
import unittest
from unittest.mock import patch

from farm_yield.database import DatabaseUnavailable
from farm_yield.ml.artifacts import ModelUnavailable
from farm_yield.seasons import completed_season, season_dates
from farm_yield.web import create_app


class SeasonTests(unittest.TestCase):
    def test_cross_year_leap_season(self):
        start, end = season_dates('Rabi', 2016)
        self.assertEqual(start, date(2015, 10, 1))
        self.assertEqual(end, date(2016, 3, 31))
        self.assertEqual((end - start).days + 1, 183)

    def test_completed_season_respects_data_lag(self):
        self.assertEqual(completed_season('Wheat', date(2026, 4, 2))[3], 2025)
        self.assertEqual(completed_season('Wheat', date(2026, 4, 5))[3], 2026)
        self.assertEqual(completed_season('Rice', date(2026, 12, 2))[3], 2025)
        self.assertEqual(completed_season('Rice', date(2026, 12, 5))[3], 2026)
        self.assertEqual(completed_season('Sugarcane', date(2026, 10, 22))[3], 2025)


class ApiTests(unittest.TestCase):
    def setUp(self):
        with patch('farm_yield.web.load_current', side_effect=ModelUnavailable('No verified bundle')):
            self.app = create_app({'TESTING': True, 'SECRET_KEY': 'session-' + 'fixture',
                                   'ADMIN_API_KEY': 'admin-' + 'fixture', 'SESSION_KEY_CONFIGURED': True})
        self.client = self.app.test_client()

    def test_process_health_does_not_call_database(self):
        with patch('farm_yield.web.database.check_ready') as db:
            self.assertEqual(self.client.get('/health').status_code, 200)
            db.assert_not_called()

    def test_readiness_fails_closed(self):
        with patch('farm_yield.web.database.check_ready', side_effect=DatabaseUnavailable('Unavailable')):
            response = self.client.get('/ready')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json['checks']['model'])
        self.assertFalse(response.json['checks']['database'])

    def test_invalid_inputs_are_rejected_before_upstream_calls(self):
        inputs = [[], {}, {'lat': True, 'lon': 77}, {'lat': 'NaN', 'lon': 77},
                  {'lat': 100, 'lon': 77}, {'lat': 51.5, 'lon': -0.1},
                  {'lat': 30.02, 'lon': 77.14, 'crop': 'unknown'},
                  {'lat': 30.02, 'lon': 77.14, 'crop': []}]
        with patch('farm_yield.web.fetch_weather') as weather:
            for body in inputs:
                with self.subTest(body=body):
                    self.assertEqual(self.client.post('/api/fetch_ndvi', json=body).status_code, 400)
            weather.assert_not_called()

    def test_bad_json_and_oversized_body(self):
        response = self.client.post('/api/fetch_ndvi', data='{', content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post('/api/ingest', data='x' * 262145,
                                         headers={'X-Admin-Key': 'admin-' + 'fixture'},
                                         content_type='application/json').status_code, 413)

    def test_model_unavailability_does_not_use_heuristic_or_fetch_data(self):
        with patch('farm_yield.web.fetch_weather') as weather:
            response = self.client.post('/api/fetch_ndvi', json={'lat': 30.02, 'lon': 77.14, 'crop': 'Wheat'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['status'], 'model_unavailable')
        self.assertNotIn('prediction', response.json)
        weather.assert_not_called()

    def test_history_requires_own_signed_session(self):
        with patch('farm_yield.web.database.prediction_history', return_value=[{'prediction_id': 'own'}]) as history:
            self.assertEqual(self.client.get('/api/predictions').json['predictions'], [])
            history.assert_not_called()
            with self.client.session_transaction() as session:
                session['visitor_id'] = 'visitor-one'
            self.assertEqual(self.client.get('/api/predictions').json['predictions'][0]['prediction_id'], 'own')
            history.assert_called_once_with('visitor-one')
            second = self.app.test_client()
            self.assertEqual(second.get('/api/predictions').json['predictions'], [])

    def test_ingestion_authentication_and_record_validation(self):
        with patch('farm_yield.web.database.ingest_observations') as ingest:
            self.assertEqual(self.client.post('/api/ingest', json={}).status_code, 401)
            self.assertEqual(self.client.post('/api/ingest', json={'dataset_version': 'v1', 'records': [{}]},
                                             headers={'X-Admin-Key': 'admin-' + 'fixture'}).status_code, 400)
            ingest.assert_not_called()


if __name__ == '__main__':
    unittest.main()
