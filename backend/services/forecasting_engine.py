import math
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple, List
import pandas as pd
import numpy as np
from sklearn.linear_model import PoissonRegressor, Ridge
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from backend.services.historical_service import historical_service, REGIONS

logger = logging.getLogger("neurora.forecasting")

class TimeSeriesForecastingEngine:
    def __init__(self):
        self.test_ratio = 0.20  # Chronological held-out test split (last 20% of timeline)

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Creates strictly chronological lag and meteorological features.
        Omits missing observation days to prevent data corruption.
        """
        # Filter valid observations
        data = df[df["daily_detection_count"].notna()].copy()
        data.sort_values(by="date", inplace=True)
        data.reset_index(drop=True, inplace=True)

        # Target: count at time t
        # Lag 1: count at t-1
        data["lag_1"] = data["daily_detection_count"].shift(1)
        data["lag_2"] = data["daily_detection_count"].shift(2)
        data["rolling_mean_7"] = data["daily_detection_count"].shift(1).rolling(window=7, min_periods=1).mean()
        data["rolling_std_7"] = data["daily_detection_count"].shift(1).rolling(window=7, min_periods=2).std().fillna(0.0)

        # Calendar features
        dates = pd.to_datetime(data["date"])
        data["day_of_week"] = dates.dt.dayofweek
        doy = dates.dt.dayofyear
        data["sin_doy"] = np.sin(2 * np.pi * doy / 365.25)
        data["cos_doy"] = np.cos(2 * np.pi * doy / 365.25)

        # Weather features
        data["temp_feat"] = data["mean_temp_c"].fillna(25.0)
        data["humidity_feat"] = data["mean_humidity_pct"].fillna(50.0)
        data["wind_feat"] = data["mean_wind_kmh"].fillna(12.0)
        data["precip_feat"] = data["total_precip_mm"].fillna(0.0)

        # Keep every row with a previous observed count so lag-1 evaluation uses
        # the same chronological 80/20 setup as the simple persistence benchmark.
        # Early secondary features are safely initialized from the available history.
        data["lag_2"] = data["lag_2"].fillna(data["lag_1"])
        data.dropna(subset=["lag_1", "rolling_mean_7"], inplace=True)
        data.reset_index(drop=True, inplace=True)
        return data

    def run_forecast(self, geo_id: str = "GLOBAL") -> Dict[str, Any]:
        """
        Executes chronological held-out training & evaluation,
        comparing Baseline (lag-1 persistence) with Alternative (Poisson count regression).
        Generates next-day forecast and transparent performance metrics.
        """
        df_raw = historical_service.get_series(geo_id)
        if df_raw.empty:
            return {"error": f"No data found for region {geo_id}"}

        reg_name = REGIONS.get(geo_id.upper(), {}).get("name", geo_id)
        data = self.prepare_features(df_raw)

        if len(data) < 20:
            return {"error": "Insufficient historical points for training"}

        # Strictly chronological split (No random shuffling!)
        split_idx = int(len(data) * (1.0 - self.test_ratio))
        train_df = data.iloc[:split_idx].copy()
        test_df = data.iloc[split_idx:].copy()

        feature_cols = [
            "lag_1", "lag_2", "rolling_mean_7",
            "sin_doy", "cos_doy",
            "temp_feat", "humidity_feat", "wind_feat", "precip_feat"
        ]

        X_train = train_df[feature_cols]
        y_train = train_df["daily_detection_count"].values
        X_test = test_df[feature_cols]
        y_test = test_df["daily_detection_count"].values

        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # 1. Baseline Model: Lag-1 persistence (predicts yesterday's count)
        y_pred_baseline = test_df["lag_1"].values

        # 2. Alternative Model: Poisson Count Regressor
        # Poisson regression with scaled inputs for numerical stability
        model_name = "Poisson regression"
        try:
            alt_model = PoissonRegressor(alpha=1e-2, max_iter=500, solver="lbfgs")
            alt_model.fit(X_train_scaled, y_train)
            y_pred_alt = alt_model.predict(X_test_scaled)
        except Exception as e:
            logger.warning(f"Poisson regression fallback to Ridge: {e}")
            model_name = "Ridge regression fallback"
            alt_model = Ridge(alpha=1.0)
            alt_model.fit(X_train_scaled, y_train)
            y_pred_alt = np.clip(alt_model.predict(X_test_scaled), 0, None)

        # Evaluation metrics on held-out test set
        baseline_mae = float(mean_absolute_error(y_test, y_pred_baseline))
        baseline_rmse = float(root_mean_squared_error(y_test, y_pred_baseline))

        alt_mae = float(mean_absolute_error(y_test, y_pred_alt))
        alt_rmse = float(root_mean_squared_error(y_test, y_pred_alt))

        mae_improvement_pct = round(((baseline_mae - alt_mae) / baseline_mae) * 100.0, 2) if baseline_mae > 0 else 0.0
        outperformed = alt_mae < baseline_mae

        test_start_date = test_df["date"].iloc[0]
        test_end_date = test_df["date"].iloc[-1]
        n_eval_samples = len(test_df)

        # Next-Day Forecast Generation
        last_row = data.iloc[-1]
        latest_observed_count = float(last_row["daily_detection_count"])

        next_features = pd.DataFrame([{
            "lag_1": latest_observed_count,
            "lag_2": float(last_row["lag_1"]),
            "rolling_mean_7": float(data.tail(7)["daily_detection_count"].mean()),
            "sin_doy": float(last_row["sin_doy"]),
            "cos_doy": float(last_row["cos_doy"]),
            "temp_feat": float(last_row["temp_feat"]),
            "humidity_feat": float(last_row["humidity_feat"]),
            "wind_feat": float(last_row["wind_feat"]),
            "precip_feat": float(last_row["precip_feat"])
        }])

        next_day_baseline = int(round(latest_observed_count))
        next_features_scaled = scaler.transform(next_features)
        next_day_alt_raw = float(alt_model.predict(next_features_scaled)[0])
        next_day_alt = int(round(max(0.0, next_day_alt_raw)))

        # Recent timeline data for chart plotting
        recent_plot = []
        for _, r in test_df.tail(30).iterrows():
            r_feat_scaled = scaler.transform(pd.DataFrame([r[feature_cols]]))
            recent_plot.append({
                "date": r["date"],
                "actual_count": int(r["daily_detection_count"]),
                "baseline_pred": int(round(r["lag_1"])),
                "alt_pred": int(round(float(alt_model.predict(r_feat_scaled)[0])))
            })

        # Transparent narrative explanation
        if alt_mae < baseline_mae:
            performance_narrative = (
                f"{model_name} had lower held-out MAE than lag-1 persistence: "
                f"{alt_mae:.1f} vs {baseline_mae:.1f} detections ({mae_improvement_pct:.1f}% lower)."
            )
        elif alt_mae > baseline_mae:
            delta = alt_mae - baseline_mae
            if baseline_mae > 0:
                performance_narrative = (
                    f"{model_name} did not beat lag-1 persistence on held-out MAE: "
                    f"{alt_mae:.1f} vs {baseline_mae:.1f} detections ({delta / baseline_mae * 100:.1f}% higher)."
                )
            else:
                performance_narrative = (
                    f"{model_name} did not beat lag-1 persistence on held-out MAE: "
                    f"{alt_mae:.1f} vs {baseline_mae:.1f} detections."
                )
        else:
            performance_narrative = (
                f"{model_name} and lag-1 persistence tied on held-out MAE at {alt_mae:.1f} detections."
            )

        return {
            "geographic_unit": {
                "id": geo_id.upper(),
                "name": reg_name
            },
            "next_day_forecast": {
                "date": (pd.to_datetime(data["date"].iloc[-1]) + timedelta(days=1)).strftime("%Y-%m-%d"),
                "prediction": next_day_baseline,
                "alternative_prediction": next_day_alt,
                "baseline_prediction": next_day_baseline,
                "model_name": "Lag-1 persistence",
                "latest_observed_count": int(latest_observed_count),
                "trend_vs_yesterday": "Increasing" if next_day_baseline > latest_observed_count else "Decreasing" if next_day_baseline < latest_observed_count else "Stable"
            },
            "model_comparison": {
                "baseline_model": {
                    "name": "Lag-1 Persistence Benchmark",
                    "description": "Predicts count(t) = count(t-1)",
                    "held_out_mae": round(baseline_mae, 2),
                    "held_out_rmse": round(baseline_rmse, 2)
                },
                "alternative_model": {
                    "name": model_name,
                    "description": "Poisson regression using recent counts, seasonal terms, and surface meteorology" if model_name == "Poisson regression" else "Ridge regression fallback using the same input features",
                    "held_out_mae": round(alt_mae, 2),
                    "held_out_rmse": round(alt_rmse, 2)
                },
                "alternative_outperformed_baseline": outperformed,
                "mae_improvement_pct": mae_improvement_pct,
                "narrative": performance_narrative
            },
            "evaluation_protocol": {
                "split_type": "Chronological Held-Out (Strictly Time-Ordered, Zero Data Leakage)",
                "test_period": {
                    "start_date": test_start_date,
                    "end_date": test_end_date,
                    "evaluated_days": n_eval_samples
                },
                "training_samples": len(train_df),
                "test_samples": len(test_df)
            },
            "recent_series_plot": recent_plot,
            "scientific_limitations": (
                "FORECASTING LIMITATIONS: This model forecasts satellite-observed active fire detections (VIIRS/MODIS), "
                "NOT total ground fire incidents. Detections depend on orbital revisit geometry, cloud cover attenuation, "
                "and fire radiative power. Days with sensor outages or orbital coverage gaps are excluded from training rather "
                "than treated as true zeros."
            )
        }

forecasting_engine = TimeSeriesForecastingEngine()
