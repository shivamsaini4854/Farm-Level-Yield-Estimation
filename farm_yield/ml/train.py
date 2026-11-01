"""Frozen-year model comparison with train-only preprocessing and serving parity."""

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import random

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from farm_yield.features import MONTHLY_COLUMNS, WEATHER_COLUMNS, build_feature_row, feature_columns
from farm_yield.ml.artifacts import predict
from farm_yield.paths import CURRENT, GEO_DATA, PROCESSED_DATA, RAW_DATA, RUNS
from farm_yield.seasons import CROPS, season_months


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_dataset():
    labels = pd.read_csv(PROCESSED_DATA / 'labels.csv')
    weather = pd.read_csv(PROCESSED_DATA / 'monthly_weather.csv').set_index(['State', 'District', 'month'])
    cache = RAW_DATA / 'satellite' / 'point-buffer-v1'
    satellite, manifest = {}, {}
    expected_ids = set(pd.read_csv(GEO_DATA / 'district_locations.csv').shape_id)
    for month in season_months(date(2015, 7, 1), date(2019, 12, 31)):
        path = cache / (month.isoformat() + '.json')
        doc = json.loads(path.read_text(encoding='utf-8'))
        records = doc['records']
        if len(records) != len(expected_ids) or {r['location_id'] for r in records} != expected_ids:
            raise ValueError('Satellite location accounting does not match the accepted geography.')
        manifest[str(path.relative_to(RAW_DATA))] = file_hash(path)
        for record in records:
            key = (record['location_id'], record['month'])
            if key in satellite:
                raise ValueError('Duplicate satellite key.')
            satellite[key] = record
    frames, seasons = [], []
    for row in labels.to_dict('records'):
        start, end = date.fromisoformat(row['start']), date.fromisoformat(row['end'])
        records = []
        for month in season_months(start, end):
            key = (row['State'], row['District'], month.isoformat())
            record = weather.loc[key].to_dict()
            record['days'] = int(record['days'])
            record.update(satellite[(row['shape_id'], month.isoformat())])
            records.append(record)
        frames.append(build_feature_row(records, row['Crop'], start, end))
        seasons.append(records)
    features = pd.concat(frames, ignore_index=True)
    assert features.columns.tolist() == feature_columns()
    assert not labels.duplicated(['State', 'District', 'Crop', 'Season', 'harvest_year']).any()
    for name in ('labels.csv', 'monthly_weather.csv', 'dataset_audit.json'):
        manifest[name] = file_hash(PROCESSED_DATA / name)
    return labels, features, seasons, manifest


def preprocessing():
    return Pipeline([('imputer', SimpleImputer(strategy='median', keep_empty_features=True)),
                     ('scaler', StandardScaler())])


def metrics(labels, predictions, scales):
    rows = []
    for crop in CROPS:
        mask = labels.Crop.eq(crop).to_numpy()
        y, p = labels.Yield.to_numpy()[mask], np.asarray(predictions)[mask]
        if len(y) < 2:
            raise ValueError(f'Insufficient evaluation coverage for {crop}.')
        rows.append({'crop': crop, 'count': len(y), 'mae_t_ha': float(mean_absolute_error(y, p)),
                     'rmse_t_ha': float(np.sqrt(mean_squared_error(y, p))), 'r2': float(r2_score(y, p)),
                     'normalized_mae': float(mean_absolute_error(y, p) / scales[crop])})
    return {'crop_balanced_normalized_mae': float(np.mean([r['normalized_mae'] for r in rows])),
            'count': len(labels), 'per_crop': rows}


def lstm_predictions(x_train, x_valid, x_test, y_train, valid_labels, scales, directory):
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    prep = preprocessing().fit(x_train)
    per_month = 2 * len(MONTHLY_COLUMNS) + 1

    def tensor(frame):
        values = prep.transform(frame).astype('float32')
        monthly = values[:, :12 * per_month].reshape(-1, 12, per_month)
        context = np.repeat(values[:, None, 12 * per_month:], 12, axis=1)
        lengths = frame[[f'm{m:02d}_in_season' for m in range(1, 13)]].sum(axis=1).to_numpy().astype('int64')
        return torch.from_numpy(np.concatenate([monthly, context], axis=2)), torch.from_numpy(lengths)

    class SequenceModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(per_month + len(CROPS) + 3, 32, batch_first=True)
            self.output = nn.Linear(32, 1)

        def forward(self, values, lengths):
            hidden, _ = self.lstm(values)
            return self.output(hidden[torch.arange(len(values)), lengths - 1]).squeeze(1)

    train_values, train_lengths = tensor(x_train)
    valid_values, valid_lengths = tensor(x_valid)
    test_values, test_lengths = tensor(x_test)
    model = SequenceModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    loader = DataLoader(TensorDataset(train_values, train_lengths, torch.tensor(y_train, dtype=torch.float32)),
                        batch_size=128, shuffle=True, generator=torch.Generator().manual_seed(42))
    best, stale, history = float('inf'), 0, []
    checkpoint = directory / 'checkpoints'
    checkpoint.mkdir()
    for epoch in range(20):
        model.train()
        for values, lengths, targets in loader:
            optimizer.zero_grad()
            loss = nn.functional.mse_loss(model(values, lengths), targets)
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            estimates = model(valid_values, valid_lengths).numpy() * valid_labels.Crop.map(scales).to_numpy()
        score = metrics(valid_labels, estimates, scales)['crop_balanced_normalized_mae']
        history.append({'epoch': epoch + 1, 'validation_score': score})
        if score < best:
            best, stale = score, 0
            torch.save({'state_dict': model.state_dict(), 'hidden_size': 32, 'seed': 42,
                        'input_size': per_month + len(CROPS) + 3, 'epoch': epoch + 1}, checkpoint / 'lstm.pt')
        else:
            stale += 1
            if stale >= 3:
                break
    model.load_state_dict(torch.load(checkpoint / 'lstm.pt', map_location='cpu', weights_only=True)['state_dict'])
    model.eval()
    with torch.no_grad():
        valid, test = model(valid_values, valid_lengths).numpy(), model(test_values, test_lengths).numpy()
    joblib.dump(prep, checkpoint / 'lstm_preprocessing.pkl')
    return valid, test, history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--promote', action='store_true', help='Promote only after all comparison and parity gates pass.')
    args = parser.parse_args()
    labels, features, seasons, source_manifest = load_dataset()
    train = labels.harvest_year.isin([2016, 2017]).to_numpy()
    valid = labels.harvest_year.eq(2018).to_numpy()
    test = labels.harvest_year.eq(2019).to_numpy()
    assert (train.astype(int) + valid + test == 1).all()
    scales = labels[train].groupby('Crop').Yield.median().to_dict()
    if set(scales) != set(CROPS) or any(value <= 0 for value in scales.values()):
        raise ValueError('Every crop requires positive training median coverage.')
    y = labels.Yield.to_numpy() / labels.Crop.map(scales).to_numpy()
    from xgboost import XGBRegressor
    candidates = {
        'CropSeasonMedian': DummyRegressor(strategy='constant', constant=1.0),
        'Ridge': Ridge(alpha=10),
        # Fixed accumulation order is required for exact serialized prediction parity.
        'RandomForest': RandomForestRegressor(n_estimators=120, max_depth=14, min_samples_leaf=3, random_state=42, n_jobs=1),
        'GradientBoosting': GradientBoostingRegressor(n_estimators=120, max_depth=3, random_state=42),
        'XGBoost': XGBRegressor(n_estimators=180, max_depth=4, learning_rate=.05, random_state=42, n_jobs=2),
    }
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = RUNS / run_id
    directory.mkdir(parents=True)
    report = {'run_id': run_id, 'seed': 42, 'unit': 'tonnes/hectare', 'evaluation_unit': 'district',
              'train_years': [2016, 2017], 'validation_year': 2018, 'retrospective_backtest_year': 2019,
              'source_manifest': source_manifest, 'models': {}, 'ablations': {}}
    predictions = labels[['State', 'District', 'shape_id', 'Crop', 'Season', 'harvest_year', 'Yield']].copy()
    models = {}
    for name, estimator in candidates.items():
        pipeline = Pipeline([('preprocessing', preprocessing()), ('model', estimator)])
        pipeline.fit(features[train], y[train])
        raw = pipeline.predict(features) * labels.Crop.map(scales).to_numpy()
        report['models'][name] = {'validation': metrics(labels[valid], raw[valid], scales),
                                  'backtest': metrics(labels[test], raw[test], scales),
                                  'valid_predictions': bool(np.isfinite(raw).all() and (raw >= 0).all())}
        models[name] = pipeline
        predictions[name] = raw
        print(name, report['models'][name]['validation']['crop_balanced_normalized_mae'], flush=True)
    lv, lt, history = lstm_predictions(features[train], features[valid], features[test], y[train], labels[valid], scales, directory)
    report['models']['LSTM'] = {'validation': metrics(labels[valid], lv * labels[valid].Crop.map(scales), scales),
                               'backtest': metrics(labels[test], lt * labels[test].Crop.map(scales), scales), 'epochs': history}
    predictions['LSTM'] = np.nan
    predictions.loc[valid, 'LSTM'] = lv * labels[valid].Crop.map(scales)
    predictions.loc[test, 'LSTM'] = lt * labels[test].Crop.map(scales)
    eligible = [name for name in candidates if report['models'][name]['valid_predictions']]
    winner = min(eligible, key=lambda name: report['models'][name]['validation']['crop_balanced_normalized_mae'])
    for name, columns in [('weather_only', WEATHER_COLUMNS), ('weather_ndvi', WEATHER_COLUMNS + ('ndvi',))]:
        selected = feature_columns(columns)
        reduced = features[selected]
        model = Pipeline([('preprocessing', preprocessing()), ('model', clone(candidates[winner]))])
        model.fit(reduced[train], y[train])
        raw = model.predict(reduced) * labels.Crop.map(scales).to_numpy()
        report['ablations'][name] = {'validation': metrics(labels[valid], raw[valid], scales),
                                     'backtest': metrics(labels[test], raw[test], scales)}
    availability = {column: int(features[[f'm{m:02d}_{column}_available' for m in range(1, 13)]].to_numpy().sum())
                    for column in MONTHLY_COLUMNS}
    report['available_months'] = availability
    coverage = []
    for (crop, year), group in labels.groupby(['Crop', 'harvest_year']):
        subset = features.loc[group.index]
        months = int(subset[[f'm{m:02d}_in_season' for m in range(1, 13)]].to_numpy().sum())
        coverage.append({'crop': crop, 'harvest_year': int(year), 'labels': len(group), 'season_months': months,
            'available_months': {column: int(subset[[f'm{m:02d}_{column}_available' for m in range(1, 13)]].to_numpy().sum())
                                for column in MONTHLY_COLUMNS}})
    report['coverage_by_crop_year'] = coverage
    report['selected_tabular_model'] = winner
    limits = ['District labels do not validate field-level accuracy.',
              '2019 is a retrospective backtest; years were inspected in earlier experiments.',
              'Fixed reporting seasons and district reference-point buffers are proxies, without crop masks.',
              'Geographic exclusions limit national coverage; see dataset_audit.json.',
              'Sentinel-2 TOA comparability, satellite missingness and present-day boundaries are experimental limits.',
              '8/16-day satellite composites can extend up to 15 days beyond the reporting-season boundary; this is retrospective estimation.',
              'Current-season and post-2019 performance have not been evaluated.']
    metadata = {'schema_version': 2, 'monthly_columns': list(MONTHLY_COLUMNS),
                'feature_columns': feature_columns(), 'target_scales': scales, 'model_name': winner,
                'run_id': run_id, 'verified': False, 'evidence_limits': limits,
                'harvest_years': [2016, 2017, 2018, 2019], 'unit': 'tonnes/hectare'}
    observations = {}
    for label, records in zip(labels.to_dict('records'), seasons):
        observations.setdefault(label['shape_id'], {}).update({r['month']: r for r in records})
    bundle = {'pipeline': models[winner], 'metadata': metadata, 'observations': observations}
    # Verify the actual shared inference path and a serialized round trip on each crop.
    for crop in CROPS:
        index = labels.index[test & labels.Crop.eq(crop).to_numpy()][0]
        row = labels.iloc[index]
        actual = predict(bundle, seasons[index], crop, date.fromisoformat(row.start), date.fromisoformat(row.end))
        assert actual == round(float(predictions.loc[index, winner]), 2)
    report['parity_passed'] = False
    (directory / 'evaluation.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    (directory / 'metadata.json').write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding='utf-8')
    predictions.to_csv(directory / 'predictions.csv', index=False)
    joblib.dump(bundle, directory / 'bundle.pkl')
    restored = joblib.load(directory / 'bundle.pkl')
    np.testing.assert_allclose(restored['pipeline'].predict(features[test]), models[winner].predict(features[test]), rtol=0, atol=0)
    restored['metadata']['verified'] = True
    metadata = restored['metadata']
    joblib.dump(restored, directory / 'bundle.pkl')
    report['parity_passed'] = True
    (directory / 'evaluation.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    (directory / 'metadata.json').write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding='utf-8')
    features.to_csv(PROCESSED_DATA / 'model_features.csv', index=False)
    if args.promote:
        temporary = CURRENT.with_suffix('.tmp')
        temporary.write_text(json.dumps({'run_id': run_id, 'bundle_sha256': file_hash(directory / 'bundle.pkl')}, indent=2), encoding='utf-8')
        temporary.replace(CURRENT)
    print(f'PASS: {run_id}, selected {winner}; promotion={args.promote}', flush=True)


if __name__ == '__main__':
    main()
