"""
Audit the real-data congestion model for target leakage.

Checks:
- Random Forest feature importances from the original model feature set.
- Raw correlations between Congestion Level and key numeric fields.
- Retrains without leakage-risk engineered/near-target fields when implicated.

The audit uses the same filtered dataset and same 80/20 held-out split as
train_congestion_model.py.
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
AUDIT_REPORT_FILE = OUTPUT_DIR / "congestion_model_leakage_audit.txt"
HONEST_MODEL_FILE = OUTPUT_DIR / "bangalore_congestion_model_no_leakage.joblib"

LOCATIONS = [
    "Silk Board Junction",
    "Marathahalli Bridge",
    "Sarjapur Road",
]

TARGET = "Congestion Level"
LEAKAGE_CORRELATION_THRESHOLD = 0.85

ORIGINAL_NUMERIC_FEATURES = [
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

INDEPENDENT_NUMERIC_FEATURES = [
    "Traffic Volume",
    "Average Speed",
    "Incident Reports",
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


def rmse(y_true: pd.Series, y_pred: np.ndarray) -> float:
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


def build_preprocessor(numeric_features: list[str]) -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric_features,
            ),
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                CATEGORICAL_FEATURES,
            ),
        ]
    )


def build_linear_model(numeric_features: list[str]) -> Pipeline:
    return Pipeline(
        steps=[
            ("preprocess", build_preprocessor(numeric_features)),
            ("model", LinearRegression()),
        ]
    )


def build_random_forest(numeric_features: list[str]) -> Pipeline:
    return Pipeline(
        steps=[
            ("preprocess", build_preprocessor(numeric_features)),
            (
                "model",
                RandomForestRegressor(
                    n_estimators=100,
                    min_samples_leaf=2,
                    random_state=42,
                    n_jobs=1,
                ),
            ),
        ]
    )


def evaluate(model: Pipeline, X_test: pd.DataFrame, y_test: pd.Series) -> dict[str, float]:
    predictions = model.predict(X_test)
    return {
        "r2": float(r2_score(y_test, predictions)),
        "rmse": rmse(y_test, predictions),
    }


def transformed_feature_importances(model: Pipeline) -> pd.DataFrame:
    preprocessor = model.named_steps["preprocess"]
    forest = model.named_steps["model"]
    names = preprocessor.get_feature_names_out()
    return pd.DataFrame(
        {
            "feature": names,
            "importance": forest.feature_importances_,
        }
    ).sort_values("importance", ascending=False, ignore_index=True)


def aggregate_importances(importances: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in importances.iterrows():
        feature = row["feature"]
        if feature.startswith("numeric__"):
            source_feature = feature.removeprefix("numeric__")
        elif feature.startswith("categorical__"):
            source_feature = feature.removeprefix("categorical__").split("_", 1)[0]
        else:
            source_feature = feature
        rows.append((source_feature, row["importance"]))

    aggregated = (
        pd.DataFrame(rows, columns=["source_feature", "importance"])
        .groupby("source_feature", as_index=False)["importance"]
        .sum()
        .sort_values("importance", ascending=False, ignore_index=True)
    )
    return aggregated


def correlation_table(filtered: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for feature in [
        "Road Capacity Utilization",
        "Travel Time Index",
        "Traffic Volume",
        "Average Speed",
    ]:
        corr = filtered[TARGET].corr(filtered[feature])
        rows.append(
            {
                "feature": feature,
                "correlation_with_target": float(corr),
                "abs_correlation": abs(float(corr)),
                "leakage_risk": abs(float(corr)) > LEAKAGE_CORRELATION_THRESHOLD,
            }
        )
    return pd.DataFrame(rows).sort_values("abs_correlation", ascending=False, ignore_index=True)


def format_table(df: pd.DataFrame, max_rows: int | None = None) -> str:
    shown = df if max_rows is None else df.head(max_rows)
    return shown.to_string(index=False)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    filtered = load_filtered_data()
    X_original = filtered[ORIGINAL_NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    X_independent = filtered[INDEPENDENT_NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    y = filtered[TARGET]

    train_idx, test_idx = train_test_split(
        filtered.index,
        test_size=0.20,
        random_state=42,
        stratify=filtered["Road/Intersection Name"],
    )

    X_original_train = X_original.loc[train_idx]
    X_original_test = X_original.loc[test_idx]
    X_independent_train = X_independent.loc[train_idx]
    X_independent_test = X_independent.loc[test_idx]
    y_train = y.loc[train_idx]
    y_test = y.loc[test_idx]

    original_linear = build_linear_model(ORIGINAL_NUMERIC_FEATURES).fit(X_original_train, y_train)
    original_forest = build_random_forest(ORIGINAL_NUMERIC_FEATURES).fit(X_original_train, y_train)
    independent_linear = build_linear_model(INDEPENDENT_NUMERIC_FEATURES).fit(X_independent_train, y_train)
    independent_forest = build_random_forest(INDEPENDENT_NUMERIC_FEATURES).fit(X_independent_train, y_train)

    original_metrics = {
        "Linear Regression": evaluate(original_linear, X_original_test, y_test),
        "Random Forest": evaluate(original_forest, X_original_test, y_test),
    }
    independent_metrics = {
        "Linear Regression": evaluate(independent_linear, X_independent_test, y_test),
        "Random Forest": evaluate(independent_forest, X_independent_test, y_test),
    }

    transformed_importances = transformed_feature_importances(original_forest)
    aggregated_importance = aggregate_importances(transformed_importances)
    correlations = correlation_table(filtered)

    implicated = []
    dominant_features = set(aggregated_importance.head(3)["source_feature"])
    for feature in ["Road Capacity Utilization", "Travel Time Index"]:
        high_corr = bool(correlations.loc[correlations["feature"] == feature, "leakage_risk"].iloc[0])
        dominant = feature in dominant_features
        if high_corr and dominant:
            implicated.append(feature)

    joblib.dump(
        {
            "model": independent_forest,
            "model_name": "Random Forest without leakage-risk features",
            "target": TARGET,
            "features": INDEPENDENT_NUMERIC_FEATURES + CATEGORICAL_FEATURES,
            "removed_features": [
                "Travel Time Index",
                "Road Capacity Utilization",
                "Environmental Impact",
            ],
            "metrics": independent_metrics,
            "locations": LOCATIONS,
            "note": (
                "This model excludes Travel Time Index and Road Capacity Utilization "
                "because leakage audit found near-target correlation/dominance risk. "
                "Environmental Impact is also excluded from the independent feature set "
                "because it appears derived from traffic conditions rather than an "
                "exogenous input."
            ),
        },
        HONEST_MODEL_FILE,
    )

    sample = filtered.loc[test_idx, ["Date", "Road/Intersection Name", "Traffic Volume", "Average Speed"]].copy()
    sample["actual_congestion_level"] = y_test
    sample["with_leaky_features_prediction"] = original_forest.predict(X_original_test)
    sample["without_leaky_features_prediction"] = independent_forest.predict(X_independent_test)
    sample = sample.head(5)
    sample["Date"] = sample["Date"].dt.date

    metric_rows = []
    for model_name in ["Linear Regression", "Random Forest"]:
        metric_rows.append(
            {
                "model": model_name,
                "feature_set": "with suspected leakage features",
                "r2": original_metrics[model_name]["r2"],
                "rmse": original_metrics[model_name]["rmse"],
            }
        )
        metric_rows.append(
            {
                "model": model_name,
                "feature_set": "without leakage-risk features",
                "r2": independent_metrics[model_name]["r2"],
                "rmse": independent_metrics[model_name]["rmse"],
            }
        )
    metric_table = pd.DataFrame(metric_rows)

    lines = [
        "=" * 72,
        "CONGESTION MODEL LEAKAGE AUDIT",
        "=" * 72,
        "",
        f"Filtered rows: {len(filtered):,}",
        f"Target: {TARGET}",
        f"Same split: 80/20, random_state=42, stratified by Road/Intersection Name",
        "",
        "RAW CORRELATIONS WITH TARGET",
        "-" * 40,
        format_table(correlations),
        "",
        f"Leakage threshold: absolute correlation > {LEAKAGE_CORRELATION_THRESHOLD}",
        "",
        "ORIGINAL RANDOM FOREST FEATURE IMPORTANCE",
        "-" * 40,
        "Aggregated to original input columns:",
        format_table(aggregated_importance),
        "",
        "Top transformed features:",
        format_table(transformed_importances.head(15)),
        "",
        "DOMINANT DRIVERS",
        "-" * 40,
        ", ".join(aggregated_importance.head(3)["source_feature"].tolist()),
        "",
        "LEAKAGE DECISION",
        "-" * 40,
    ]

    if implicated:
        lines.append(
            "Confirmed leakage risk: "
            + ", ".join(implicated)
            + " are both highly correlated with the target and among the top drivers."
        )
    else:
        lines.append(
            "No Road Capacity Utilization / Travel Time Index feature met both the "
            "high-correlation and top-driver criteria."
        )

    lines.extend(
        [
            (
                "Retrained independent model without Travel Time Index and Road "
                "Capacity Utilization. Environmental Impact was also excluded from "
                "the independent set because it appears derived from traffic "
                "conditions and is not a clean exogenous predictor."
            ),
            "",
            "SIDE-BY-SIDE HELD-OUT METRICS",
            "-" * 40,
            format_table(metric_table),
            "",
            "SAMPLE TEST PREDICTIONS",
            "-" * 40,
            format_table(sample),
            "",
            "SAVED HONEST MODEL",
            "-" * 40,
            str(HONEST_MODEL_FILE),
            "",
            "Machine-readable summary:",
            json.dumps(
                {
                    "correlations": correlations.to_dict(orient="records"),
                    "aggregated_feature_importance": aggregated_importance.to_dict(orient="records"),
                    "original_metrics": original_metrics,
                    "without_leakage_risk_metrics": independent_metrics,
                    "implicated_features": implicated,
                    "saved_model": str(HONEST_MODEL_FILE),
                },
                indent=2,
            ),
            "",
        ]
    )

    AUDIT_REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(AUDIT_REPORT_FILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
