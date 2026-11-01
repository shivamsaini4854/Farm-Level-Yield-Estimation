"""Flask routes for completed-season research estimates and isolated history."""

import hmac
import json
import logging
import os
import re
import secrets
from datetime import timedelta
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException

from farm_yield import database
from farm_yield.acquisition.live import ObservationsUnavailable
from farm_yield.coordinates import normalize_and_validate_coordinates
from farm_yield.features import SATELLITE_COLUMNS, validate_monthly_record, weather_summary
from farm_yield.geography import districts, resolve_district
from farm_yield.ml.artifacts import ModelUnavailable, load_current, predict
from farm_yield.paths import ENV_FILE, GEO_DATA
from farm_yield.seasons import CROPS, completed_season, season_months

load_dotenv(ENV_FILE)
logger = logging.getLogger(__name__)


def create_app(config=None):
    application = Flask(__name__)
    configured_secret = os.getenv('SESSION_SECRET')
    application.config.update(
        SECRET_KEY=configured_secret or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=bool(os.getenv('RENDER')),
        MAX_CONTENT_LENGTH=262144, ADMIN_API_KEY=os.getenv('ADMIN_API_KEY'),
        SESSION_KEY_CONFIGURED=bool(configured_secret),
    )
    if config:
        application.config.update(config)
    if not configured_secret and not application.config.get('TESTING'):
        logger.warning('Using a temporary local session key; set SESSION_SECRET before deployment.')
    try:
        application.extensions['yield_bundle'] = load_current()
        application.extensions['model_error'] = None
    except Exception as exc:
        application.extensions['yield_bundle'] = None
        application.extensions['model_error'] = 'No verified model bundle is available.'
        logger.warning('Model readiness failed (%s)', type(exc).__name__)

    @application.get('/health')
    def health():
        return jsonify(status='ok')

    @application.get('/ready')
    def ready():
        checks = {'model': application.extensions['yield_bundle'] is not None,
                  'session_key': application.config['SESSION_KEY_CONFIGURED'], 'database': False,
                  'geography': False}
        try:
            checks['geography'] = bool(districts())
        except (OSError, ValueError, KeyError, TypeError):
            logger.error('District geography is unavailable.')
        try:
            checks['database'] = database.check_ready()
        except database.DatabaseUnavailable:
            pass
        success = all(checks.values())
        return jsonify(status='ready' if success else 'not_ready', checks=checks), 200 if success else 503

    @application.route('/', methods=['GET', 'POST'])
    def home():
        lat = lon = None
        if request.method == 'POST':
            try:
                lat, lon = normalize_and_validate_coordinates(request.form.get('latitude'), request.form.get('longitude'), True)
            except ValueError:
                pass
        return render_template('index.html', weather=None, submitted_lat=lat, submitted_lon=lon,
                               model_ready=application.extensions['yield_bundle'] is not None,
                               supported_year=max(application.extensions['yield_bundle']['metadata']['harvest_years'])
                               if application.extensions['yield_bundle'] else None)

    @application.post('/api/fetch_ndvi')
    def fetch_ndvi():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('Request body must be a JSON object.')
        lat, lon = normalize_and_validate_coordinates(data.get('lat'), data.get('lon'), True)
        crop = data.get('crop', 'Sugarcane')
        if not isinstance(crop, str) or crop not in CROPS:
            raise ValueError('Unsupported crop.')
        bundle = application.extensions['yield_bundle']
        if bundle is None:
            raise ModelUnavailable(application.extensions['model_error'])
        start, end, season, harvest_year = completed_season(crop, supported_years=bundle['metadata']['harvest_years'])
        district = resolve_district(lat, lon)
        observed = bundle['observations'].get(district['shape_id'], {})
        months = [month.isoformat() for month in season_months(start, end)]
        if any(month not in observed for month in months):
            raise ObservationsUnavailable('Verified historical observations are unavailable for this district and season.')
        records = [observed[month] for month in months]
        prediction = predict(bundle, records, crop, start, end)
        available = {column: sum(r.get(column) is not None for r in records) for column in SATELLITE_COLUMNS}
        ndvi = [r['ndvi'] for r in records if r.get('ndvi') is not None]
        alerts = [{'code': 'district_labels', 'message': 'Evaluation uses district yields; accuracy for individual fields is unverified.'}]
        alerts.append({'code': 'retrospective_window', 'message': 'Satellite composites may extend up to 15 days past the reporting season; this is a historical completed-season analysis.'})
        if any(count < len(records) for count in available.values()):
            alerts.append({'code': 'missing_satellite', 'message': 'Some satellite inputs were unavailable; the saved training imputer was used.'})
        payload = {
            'status': 'success', 'prediction_id': str(uuid4()), 'prediction': prediction,
            'crop': crop, 'season': season, 'harvest_year': harvest_year,
            'season_status': 'completed', 'model': bundle['metadata']['model_name'],
            'model_version': bundle['metadata']['run_id'], 'evaluation_unit': 'district',
            'district': district['district'], 'observation_source': 'verified historical district reference-point cache',
            'analysis_mode': 'historical_replay',
            'ndvi': round(sum(ndvi) / len(ndvi), 4) if ndvi else None,
            'weather': weather_summary(records), 'feature_availability': available,
            'season_window': {'start': start.isoformat(), 'end': end.isoformat()},
            'satellite_temporal_support': {'start': start.isoformat(), 'latest_possible_end': (end + timedelta(days=15)).isoformat()},
            'alerts': alerts, 'evidence_limits': bundle['metadata']['evidence_limits'],
        }
        session.setdefault('visitor_id', secrets.token_hex(24))
        database.save_prediction(session['visitor_id'], payload)
        return jsonify(payload)

    @application.get('/api/predictions')
    def predictions():
        if 'visitor_id' not in session:
            return jsonify(predictions=[])
        return jsonify(predictions=database.prediction_history(session['visitor_id']))

    @application.post('/api/ingest')
    def ingest():
        expected = application.config['ADMIN_API_KEY']
        if not expected:
            return jsonify(error='Observation ingestion is not configured.'), 503
        supplied = request.headers.get('X-Admin-Key', '')
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            return jsonify(error='Authentication required.'), 401
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('Request body must be a JSON object.')
        version = data.get('dataset_version')
        if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', version):
            raise ValueError('dataset_version must contain 1?64 letters, numbers, dots, underscores, or hyphens.')
        records = data.get('records')
        if not isinstance(records, list) or not 1 <= len(records) <= 100:
            raise ValueError('Provide 1?100 monthly observation records.')
        for record in records:
            validate_monthly_record(record)
        inserted = database.ingest_observations(version, records)
        return jsonify(status='success', received=len(records), inserted=inserted), 201

    @application.get('/api/yield-map')
    def yield_map():
        crop = request.args.get('crop', 'Wheat')
        if crop not in CROPS:
            raise ValueError('Unsupported crop.')
        path = GEO_DATA / f'yield_map_{CROPS.index(crop)}.geojson'
        bundle = application.extensions['yield_bundle']
        if bundle is None:
            raise ModelUnavailable('No verified model bundle is available.')
        if not path.exists():
            return jsonify(error='Verified district yield map is not available.'), 503
        collection = json.loads(path.read_text(encoding='utf-8'))
        if any(f['properties']['model_version'] != bundle['metadata']['run_id'] for f in collection['features']):
            return jsonify(error='District map does not match the loaded model version.'), 503
        collection['features'] = [f for f in collection['features'] if f['properties']['crop'] == crop]
        return jsonify(collection)

    @application.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400

    @application.errorhandler(ModelUnavailable)
    def model_error(exc):
        return jsonify(error=str(exc), status='model_unavailable'), 503

    @application.errorhandler(ObservationsUnavailable)
    def observations_error(exc):
        return jsonify(error=str(exc), status='data_unavailable'), 502

    @application.errorhandler(database.DatabaseUnavailable)
    def db_error(exc):
        return jsonify(error=str(exc), status='storage_unavailable'), 503

    @application.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.description), exc.code

    @application.errorhandler(Exception)
    def unexpected(exc):
        logger.error('Request failed (%s)', type(exc).__name__)
        return jsonify(error='Analysis could not be completed.'), 500

    return application


app = create_app()
