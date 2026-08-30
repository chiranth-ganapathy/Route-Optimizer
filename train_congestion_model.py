"""
Train a small real-data congestion model from Bangalore's Traffic Pulse dataset.

Scope:
- Uses only rows for Silk Board Junction, Marathahalli Bridge, and Sarjapur Road.
- Compares linear regression and random forest regression.
- Predicts Congestion Level from measured traffic/weather/time features.
- Saves the best held-out-test model for later use.

This does not integrate with SUMO and does not fabricate ORR observations.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


PROJECT_DIR = Path(__file__).resolve().parent
DATA_FILE = PROJECT_DIR / "data" / "Banglore_traffic_Dataset.csv"
OUTPUT_DIR = PROJECT_DIR / "output"
MODEL_FILE = OUTPUT_DIR / "bangalore_congestion_model.joblib"
REPORT_FILE = OUTPUT_DIR / "congestion_model_report.txt"
PREDICTIONS_FILE = OUTPUT_DIR / "congestion_model_sample_predictions.csv"

LOCATIONS = [
    "Silk Board Junction",
    "Marathahalli Bridge",
    "Sarjapur Road",
]

TARGET = "Congestion Level"

NUMERIC_FEATURES = [
    "Traffic Volume",
    "Average Speed",
    "Travel Time Index",
    "Road Capacity Utilization",
    "Incident Reports",
    "Environmental Impact",
    "Public Transport Usage",
    "Traffic Signal Compliance",
    "Parking Usage",
    "Pedestrian and Cyclist Count",
    "year",
    "month",
    "day",
    "day_of_week",
    "is_weekend",
]

CATEGORICAL_FEATURES = [
    "Area Name",
    "Road/Intersection Name",
    "Weather Conditions",
    "Roadwork and Construction Activity",
]


def root_mean_squared_error(y_true: pd.Series, y_pred: np.ndarray) -> float:
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def load_filtered_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_FILE)
    filtered = df[df["Road/Intersection Name"].isin(LOCATIONS)].copy()
    filtered["Date"] = pd.to_datetime(filtered["Date"], errors="coerce")
    filtered["year"] = filtered["Date"].dt.year
    filtered["month"] = filtered["Date"].dt.month
    filtered["day"] = filtered["Date"].dt.day
    filtered["day_of_week"] = filtered["Date"].dt.dayofweek
    filtered["is_weekend"] = filtered["day_of_week"].isin([5, 6]).astype(int)
    return filtered


def build_preprocessor() -> ColumnTransformer:
    numeric_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    categorical_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("numeric", numeric_transformer, NUMERIC_FEATURES),
            ("categorical", categorical_transformer, CATEGORICAL_FEATURES),
        ]
    )


def train_models(X_train: pd.DataFrame, y_train: pd.Series) -> dict[str, Pipeline]:
    return {
        "Linear Regression": Pipeline(
            steps=[
                ("preprocess", build_preprocessor()),
                ("model", LinearRegression()),
            ]
        ).fit(X_train, y_train),
        "Random Forest": Pipeline(
            steps=[
                ("preprocess", build_preprocessor()),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=100,
                        max_depth=None,
                        min_samples_leaf=2,
                        random_state=42,
                        n_jobs=1,
                    ),
                ),
            ]
        ).fit(X_train, y_train),
    }


def evaluate_models(
    models: dict[str, Pipeline],
    X_test: pd.DataFrame,
    y_test: pd.Series,
) -> dict[str, dict[str, float]]:
    metrics = {}
    for name, model in models.items():
        predictions = model.predict(X_test)
        metrics[name] = {
            "r2": float(r2_score(y_test, predictions)),
            "rmse": root_mean_squared_error(y_test, predictions),
        }
    return metrics


def write_report(
    filtered: pd.DataFrame,
    metrics: dict[str, dict[str, float]],
    best_model_name: str,
    sample_predictions: pd.DataFrame,
) -> None:
    counts = filtered["Road/Intersection Name"].value_counts().reindex(LOCATIONS).fillna(0).astype(int)
    date_min = filtered["Date"].min().date()
    date_max = filtered["Date"].max().date()

    lines = [
        "=" * 72,
        "BANGALORE REAL-DATA CONGESTION MODEL",
        "=" * 72,
        "",
        "DATA FILTER",
        "-" * 40,
        f"Source CSV: {DATA_FILE}",
        f"Rows after filtering: {len(filtered):,}",
        f"Date range: {date_min} to {date_max}",
        "Rows by road/intersection:",
    ]
    for location, count in counts.items():
        lines.append(f"  {location}: {count:,}")

    lines.extend(
        [
            "",
            "TARGET AND FEATURES",
            "-" * 40,
            f"Target predicted: {TARGET}",
            "Numerical features:",
            f"  {', '.join(NUMERIC_FEATURES)}",
            "Categorical features:",
            f"  {', '.join(CATEGORICAL_FEATURES)}",
            "",
            "HELD-OUT TEST METRICS",
            "-" * 40,
        ]
    )

    for model_name, model_metrics in metrics.items():
        lines.append(
            f"{model_name}: R2={model_metrics['r2']:.4f}, RMSE={model_metrics['rmse']:.4f}"
        )

    lines.extend(
        [
            "",
            f"Best saved model by RMSE: {best_model_name}",
            f"Saved model: {MODEL_FILE}",
            "",
            "SAMPLE TEST PREDICTIONS",
            "-" * 40,
            sample_predictions.to_string(index=False),
            "",
            "HONEST SCOPE NOTE",
            "-" * 40,
            (
                "This model was trained on real Bangalore traffic rows for Silk Board "
                "Junction, Marathahalli Bridge, and Sarjapur Road only. It predicts "
                "Congestion Level from measured traffic volume, speed, capacity "
                "utilization, incident, public-transport, compliance, parking, "
                "pedestrian/cyclist, weather, roadwork, location, and date-derived "
                "features."
            ),
            (
                "The selected Kaggle dataset does not contain ORR or Outer Ring Road "
                "rows. ORR congestion behavior in this project therefore remains "
                "simulation-based, calibrated against standard road capacity and the "
                "SUMO network, while the real-data model contributes evidence for the "
                "available Bangalore corridor locations. This is a hybrid real-data "
                "+ simulation approach, not a claim that every route is directly "
                "real-data-driven."
            ),
            "",
            "Machine-readable metrics:",
            json.dumps(metrics, indent=2),
            "",
        ]
    )

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    filtered = load_filtered_data()
    if filtered.empty:
        raise RuntimeError("No rows matched the selected real-data corridor locations.")

    features = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    X = filtered[features]
    y = filtered[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.20,
        random_state=42,
        stratify=filtered["Road/Intersection Name"],
    )

    models = train_models(X_train, y_train)
    metrics = evaluate_models(models, X_test, y_test)
    best_model_name = min(metrics, key=lambda name: metrics[name]["rmse"])
    best_model = models[best_model_name]

    joblib.dump(
        {
            "model": best_model,
            "model_name": best_model_name,
            "target": TARGET,
            "features": features,
            "locations": LOCATIONS,
            "metrics": metrics,
        },
        MODEL_FILE,
    )

    sample = filtered.loc[X_test.index, ["Date"] + features].copy()
    sample["actual_congestion_level"] = y_test
    sample["predicted_congestion_level"] = best_model.predict(X_test)
    sample_predictions = sample[
        [
            "Date",
            "Road/Intersection Name",
            "Traffic Volume",
            "Average Speed",
            "Road Capacity Utilization",
            "actual_congestion_level",
            "predicted_congestion_level",
        ]
    ].head(5)
    sample_predictions["Date"] = sample_predictions["Date"].dt.date
    sample_predictions["prediction_error"] = (
        sample_predictions["predicted_congestion_level"]
        - sample_predictions["actual_congestion_level"]
    )
    sample_predictions.to_csv(PREDICTIONS_FILE, index=False)

    write_report(filtered, metrics, best_model_name, sample_predictions)
    print(REPORT_FILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
