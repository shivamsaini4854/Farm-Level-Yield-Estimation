"""
merge_and_train.py
===================
Final pipeline. Takes the three data sources and produces a trained model.

Inputs (must be in same folder):
    APY.csv                        - crop yield records
    nasa_power_seasonal.csv        - weather + soil features
    ndvi_historical_all_india.csv  - NDVI per district/crop/season/year

Outputs:
    merged_dataset.csv     - clean merged dataset (keep this)
    yield_model.pkl        - trained model
    scaler.pkl             - fitted scaler
    model_metadata.json    - feature list + metrics (Flask needs this)
    training_report.txt    - full evaluation report

Usage:
    python merge_and_train.py
"""

from farm_yield.paths import RAW_DATA, PROCESSED_DATA, RUNS

OUTPUT_DIR = RUNS / "legacy-rebuild"

import pandas as pd
import numpy as np
import json
import joblib
import os

from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# ── CONFIG ────────────────────────────────────────────────────────────────────
TOP16_CROPS = [
    'Rice', 'Maize', 'Moong(Green Gram)', 'Urad', 'Groundnut', 'Wheat',
    'Rapeseed &Mustard', 'Sugarcane', 'Arhar/Tur', 'Potato', 'Onion',
    'Gram', 'Jowar', 'Dry chillies', 'Bajra', 'Soyabean'
]

# Yield cap per crop (99th percentile from analysis — anything above is a data error)
YIELD_CAPS = {
    'Rice': 5.0, 'Maize': 8.5, 'Moong(Green Gram)': 1.4, 'Urad': 1.5,
    'Groundnut': 4.0, 'Wheat': 5.5, 'Rapeseed &Mustard': 2.2,
    'Sugarcane': 130.0, 'Arhar/Tur': 2.5, 'Potato': 35.0,
    'Onion': 35.0, 'Gram': 2.1, 'Jowar': 3.5,
    'Dry chillies': 8.0, 'Bajra': 44.0, 'Soyabean': 2.5
}

WEATHER_FEATURES = [
    'temp_mean_c', 'temp_max_c', 'temp_min_c',
    'rainfall_mm', 'humidity_pct', 'wind_speed_ms',
    'solar_radiation_mj', 'soil_moisture_root', 'soil_moisture_surface',
    'season_days'
]

TARGET = 'yield_t_ha'


# ── STEP 1: LOAD AND MERGE ────────────────────────────────────────────────────
def load_and_merge():
    print("[1/5] Loading data...")

    apy = pd.read_csv(RAW_DATA / 'APY.csv')
    apy.columns = apy.columns.str.strip()
    apy['District'] = apy['District'].str.strip()
    apy['State']    = apy['State'].str.strip()
    apy['Season']   = apy['Season'].str.strip()
    apy = apy[apy['Crop'].isin(TOP16_CROPS) & apy['Production'].notna()].copy()
    apy = apy.rename(columns={
        'Yield': 'yield_t_ha',
        'Area': 'area_ha',
        'Production': 'production_tonnes'
    })
    print(f"   APY: {len(apy)} rows")

    nasa = pd.read_csv(PROCESSED_DATA / 'nasa_power_seasonal.csv')
    # Drop et0_mm — 100% null
    if 'et0_mm' in nasa.columns:
        nasa = nasa.drop(columns=['et0_mm'])
    print(f"   NASA POWER: {len(nasa)} rows, {nasa['District'].nunique()} districts")

    ndvi = pd.read_csv(PROCESSED_DATA / 'ndvi_historical_all_india.csv')
    ndvi = ndvi.rename(columns={'year': 'Crop_Year'})
    print(f"   NDVI: {len(ndvi)} rows, {ndvi['District'].nunique()} districts")

    # Merge APY + NASA (inner — only rows where weather data exists)
    df = apy.merge(nasa, on=['State', 'District', 'Season', 'Crop_Year'], how='inner')
    print(f"   After APY+NASA merge: {len(df)} rows ({100*len(df)/len(apy):.1f}% retained)")

    # Merge NDVI (left join — keep all rows, NDVI will be NaN where unavailable)
    df = df.merge(
        ndvi[['State', 'District', 'Crop', 'Season', 'Crop_Year', 'ndvi_season_mean']],
        on=['State', 'District', 'Crop', 'Season', 'Crop_Year'],
        how='left'
    )
    ndvi_pct = df['ndvi_season_mean'].notna().mean() * 100
    print(f"   NDVI coverage: {ndvi_pct:.1f}% of rows")
    print(f"   Final merged: {df.shape}")

    return df


# ── STEP 2: CLEAN ─────────────────────────────────────────────────────────────
def clean(df):
    print("\n[2/5] Cleaning...")
    before = len(df)

    # Cap yield outliers per crop
    for crop, cap in YIELD_CAPS.items():
        mask = (df['Crop'] == crop) & (df['yield_t_ha'] > cap)
        df = df[~mask]

    # Drop rows where yield is 0 or negative
    df = df[df['yield_t_ha'] > 0]

    # Drop rows with nulls in weather features
    df = df.dropna(subset=WEATHER_FEATURES)

    after = len(df)
    print(f"   Rows before: {before}, after cleaning: {after} ({100*after/before:.1f}% kept)")
    print(f"   Crop distribution:\n{df['Crop'].value_counts().to_string()}")

    df.to_csv(PROCESSED_DATA / 'merged_dataset.csv', index=False)
    print(f"   Saved: merged_dataset.csv")
    return df


# ── STEP 3: FEATURE ENGINEERING ──────────────────────────────────────────────
def engineer_features(df):
    print("\n[3/5] Engineering features...")
    df = df.copy()

    # Temperature range
    df['temp_range_c'] = df['temp_max_c'] - df['temp_min_c']

    # Soil moisture composite (root zone weighted more — deeper = more relevant)
    df['soil_moisture_composite'] = (
        0.3 * df['soil_moisture_surface'] + 0.7 * df['soil_moisture_root']
    )

    # GDD proxy — Growing Degree Days (base 10°C, standard for most crops)
    df['gdd_proxy'] = (df['temp_mean_c'] - 10).clip(lower=0) * df['season_days']

    # Heat stress proxy
    df['heat_stress'] = (df['temp_mean_c'] - 25).clip(lower=0)

    # Aridity index — rainfall vs solar radiation (proxy for water balance)
    safe_rad = df['solar_radiation_mj'].replace(0, np.nan)
    df['aridity_index'] = df['rainfall_mm'] / safe_rad
    df['aridity_index'] = df['aridity_index'].clip(0, 10).fillna(0)

    # NDVI — fill NaN with crop-season median (not drop, to keep pre-2000 rows)
    # This way the model learns from NDVI where available
    ndvi_medians = df.groupby(['Crop', 'Season'])['ndvi_season_mean'].transform('median')
    df['ndvi_season_mean'] = df['ndvi_season_mean'].fillna(ndvi_medians)
    df['ndvi_available'] = (~df['ndvi_season_mean'].isna()).astype(int)
    # Final fallback for any remaining NaN
    df['ndvi_season_mean'] = df['ndvi_season_mean'].fillna(df['ndvi_season_mean'].median())

    # One-hot encode Crop
    crop_dummies = pd.get_dummies(df['Crop'], prefix='crop')
    df = pd.concat([df, crop_dummies], axis=1)

    # One-hot encode Season
    season_dummies = pd.get_dummies(df['Season'], prefix='season')
    df = pd.concat([df, season_dummies], axis=1)

    # Get final feature columns
    base = WEATHER_FEATURES.copy()
    engineered = ['temp_range_c', 'soil_moisture_composite', 'gdd_proxy',
                  'heat_stress', 'aridity_index', 'ndvi_season_mean', 'ndvi_available']
    dummies = [c for c in df.columns if c.startswith('crop_') or c.startswith('season_')]
    optional = ['area_ha']

    feature_cols = base + engineered + dummies + optional
    feature_cols = [f for f in feature_cols if f in df.columns]

    print(f"   Total features: {len(feature_cols)}")
    return df, feature_cols


# ── STEP 4: TRAIN ─────────────────────────────────────────────────────────────
def train(df, feature_cols):
    print("\n[4/5] Training...")

    # Temporal split — last 3 years as test (simulates predicting future seasons)
    all_years   = sorted(df['Crop_Year'].unique())
    test_years  = all_years[-3:]
    train_years = all_years[:-3]

    train_df = df[df['Crop_Year'].isin(train_years)]
    test_df  = df[df['Crop_Year'].isin(test_years)]

    print(f"   Train: {len(train_df)} rows ({train_years[0]}–{train_years[-1]})")
    print(f"   Test:  {len(test_df)} rows ({test_years[0]}–{test_years[-1]})")

    X_train = train_df[feature_cols].values
    y_train = train_df[TARGET].values
    X_test  = test_df[feature_cols].values
    y_test  = test_df[TARGET].values

    # Scale
    scaler     = StandardScaler()
    X_train_s  = scaler.fit_transform(X_train)
    X_test_s   = scaler.transform(X_test)

    # Train 3 models
    candidates = {
        'Ridge':             Ridge(alpha=1.0),
        'Random Forest':     RandomForestRegressor(
                                n_estimators=300, max_depth=20,
                                min_samples_leaf=4, max_features='sqrt',
                                random_state=42, n_jobs=-1),
        'Gradient Boosting': GradientBoostingRegressor(
                                n_estimators=400, learning_rate=0.05,
                                max_depth=6, min_samples_leaf=4,
                                subsample=0.8, random_state=42),
    }

    results   = {}
    report    = []

    best_name  = None
    best_r2    = -np.inf
    best_model = None

    for name, model in candidates.items():
        print(f"   Training {name}...", end=' ', flush=True)
        if name == 'Ridge':
            model.fit(X_train_s, y_train)
            preds = model.predict(X_test_s)
        else:
            model.fit(X_train, y_train)
            preds = model.predict(X_test)

        mae  = mean_absolute_error(y_test, preds)
        rmse = np.sqrt(mean_squared_error(y_test, preds))
        r2   = r2_score(y_test, preds)

        print(f"MAE={mae:.3f}  RMSE={rmse:.3f}  R²={r2:.4f}")
        report.append(f"{name}: MAE={mae:.4f}  RMSE={rmse:.4f}  R²={r2:.4f}")

        # Per-crop breakdown
        report.append(f"  Per-crop breakdown:")
        per_crop = {}
        for crop in TOP16_CROPS:
            mask = test_df['Crop'] == crop
            if mask.sum() < 5:
                continue
            yc = y_test[mask.values]
            pc = preds[mask.values]
            c_mae = mean_absolute_error(yc, pc)
            c_r2  = r2_score(yc, pc) if len(yc) > 1 else float('nan')
            per_crop[crop] = {'mae': round(c_mae, 4), 'r2': round(c_r2, 4), 'n': int(mask.sum())}
            report.append(f"    {crop:<25} MAE={c_mae:.3f}  R²={c_r2:.3f}  n={mask.sum()}")

        results[name] = {
            'overall_mae': round(mae, 4),
            'overall_rmse': round(rmse, 4),
            'overall_r2': round(r2, 4),
            'per_crop': per_crop,
        }

        if r2 > best_r2:
            best_r2    = r2
            best_name  = name
            best_model = model

    print(f"\n   Best model: {best_name} (R²={best_r2:.4f})")

    # Feature importance for RF
    rf = candidates['Random Forest']
    importances = rf.feature_importances_
    indices     = np.argsort(importances)[::-1][:15]
    report.append(f"\nTop 15 Feature Importances (Random Forest):")
    for i in indices:
        bar = '█' * int(importances[i] / importances[indices[0]] * 25)
        report.append(f"  {feature_cols[i]:<35} {bar:<25} {importances[i]:.4f}")

    return best_model, best_name, scaler, results, feature_cols, test_years, train_years, report


# ── STEP 5: SAVE ARTIFACTS ────────────────────────────────────────────────────
def save(model, model_name, scaler, results, feature_cols, test_years, train_years, report):
    print("\n[5/5] Saving artifacts...")

    joblib.dump(model, OUTPUT_DIR / 'yield_model.pkl')
    joblib.dump(scaler, OUTPUT_DIR / 'scaler.pkl')
    print("   yield_model.pkl ✅")
    print("   scaler.pkl ✅")

    metadata = {
        'model_name':     model_name,
        'feature_columns': feature_cols,
        'weather_features': WEATHER_FEATURES,
        'crops':          TOP16_CROPS,
        'target':         TARGET,
        'uses_scaler':    model_name == 'Ridge',
        'test_years':     [int(y) for y in test_years],
        'train_years':    [int(y) for y in train_years],
        'metrics':        results,
        'ndvi_note':      (
            'NDVI is included as a training feature. '
            'Pre-2000 rows and states outside NDVI batch have NDVI '
            'imputed with crop-season median. ndvi_available flag (0/1) '
            'indicates whether real NDVI was used for that row.'
        ),
    }
    with open(OUTPUT_DIR / 'model_metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)
    print("   model_metadata.json ✅")

    with open(OUTPUT_DIR / 'training_report.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    print("   training_report.txt ✅")

    print(f"\n{'='*55}")
    print(f"  BEST MODEL : {model_name}")
    print(f"  Overall R² : {results[model_name]['overall_r2']}")
    print(f"  Overall MAE: {results[model_name]['overall_mae']} T/Ha")
    print(f"  Features   : {len(feature_cols)}")
    print(f"  Training rows: {len([y for y in train_years])* 1} years of data")
    print(f"{'='*55}")
    print(f"\nNext: update app.py to load yield_model.pkl")
    print(f"      use predict_yield.py for the Flask integration")


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DATA.mkdir(parents=True, exist_ok=True)
    print("=" * 55)
    print("  MERGE + TRAIN PIPELINE")
    print("=" * 55)

    df                                              = load_and_merge()
    df                                              = clean(df)
    df, feature_cols                                = engineer_features(df)
    model, name, scaler, results, fc, ty, tny, rep  = train(df, feature_cols)
    save(model, name, scaler, results, fc, ty, tny, rep)


if __name__ == '__main__':
    main()
