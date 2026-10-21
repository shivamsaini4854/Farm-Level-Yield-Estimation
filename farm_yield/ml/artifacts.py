"""Load only promoted, hashed bundles; promotion never edits baseline files."""

import hashlib
import json
import math

import joblib

from farm_yield.features import build_feature_row, feature_columns
from farm_yield.paths import CURRENT, RUNS


class ModelUnavailable(RuntimeError):
    pass


def load_current():
    try:
        manifest = json.loads(CURRENT.read_text(encoding='utf-8'))
        directory = (RUNS / manifest['run_id']).resolve()
        if not directory.is_relative_to(RUNS.resolve()):
            raise ValueError('Invalid artifact location.')
        path = directory / 'bundle.pkl'
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != manifest['bundle_sha256']:
            raise ValueError('Artifact hash mismatch.')
        bundle = joblib.load(path)
        metadata = bundle['metadata']
        if metadata['schema_version'] != 2 or metadata['feature_columns'] != feature_columns(metadata['monthly_columns']):
            raise ValueError('Artifact schema mismatch.')
        if not metadata['verified']:
            raise ValueError('Artifact has not passed promotion checks.')
        return bundle
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ModelUnavailable('No verified model bundle is available.') from exc


def predict(bundle, records, crop, start, end):
    metadata = bundle['metadata']
    frame = build_feature_row(records, crop, start, end, tuple(metadata['monthly_columns']))
    if list(frame.columns) != metadata['feature_columns']:
        raise ModelUnavailable('Prediction schema does not match the artifact.')
    value = float(bundle['pipeline'].predict(frame)[0]) * metadata['target_scales'][crop]
    if not math.isfinite(value) or value < 0:
        raise ModelUnavailable('Model produced an invalid yield.')
    return round(value, 2)
