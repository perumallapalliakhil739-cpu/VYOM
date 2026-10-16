import math
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("neurora.risk")

class EnvironmentalFireRiskEngine:
    """
    Explainable Environmental Fire-Risk Assessment Engine.
    Implements a documented multi-factor fire weather & thermal anomaly framework
    grounded in recognized fire danger index principles (Fosberg FWI, McArthur FFDI components).
    """

    def evaluate_risk(
        self,
        temperature_c: Optional[float],
        relative_humidity_pct: Optional[float],
        wind_speed_kmh: Optional[float],
        precipitation_mm: Optional[float] = 0.0,
        forecast_precip_mm: Optional[float] = 0.0,
        nearby_hotspot_count: int = 0,
        nearby_total_frp: float = 0.0,
        location_name: str = "Selected Location"
    ) -> Dict[str, Any]:
        """
        Calculates an explainable Environmental Fire-Risk Index (EFRI) from 0 to 100
        and categorizes into RED, ORANGE, or GREEN alert status.
        """
        # Default fallbacks if weather inputs are unavailable
        t = temperature_c if temperature_c is not None else 20.0
        rh = relative_humidity_pct if relative_humidity_pct is not None else 50.0
        w = wind_speed_kmh if wind_speed_kmh is not None else 10.0
        p = precipitation_mm if precipitation_mm is not None else 0.0
        fp = forecast_precip_mm if forecast_precip_mm is not None else 0.0

        # 1. Temperature Subscore (0 - 100)
        # Cold (< 10°C) -> low risk; High (> 35°C) -> high risk
        if t <= 10.0:
            temp_score = max(0.0, t * 1.5)
        elif t <= 25.0:
            temp_score = 15.0 + (t - 10.0) * 2.33  # 15 to 50
        elif t <= 38.0:
            temp_score = 50.0 + (t - 25.0) * 3.07  # 50 to 90
        else:
            temp_score = min(100.0, 90.0 + (t - 38.0) * 2.5)

        # 2. Relative Humidity Subscore (0 - 100) [Inverted: lower RH = higher risk]
        # Fine fuels equilibrate rapidly with atmospheric humidity
        if rh >= 75.0:
            rh_score = max(0.0, (100.0 - rh) * 0.4)
        elif rh >= 45.0:
            rh_score = 10.0 + (75.0 - rh) * 1.0  # 10 to 40
        elif rh >= 25.0:
            rh_score = 40.0 + (45.0 - rh) * 1.75  # 40 to 75
        elif rh >= 10.0:
            rh_score = 75.0 + (25.0 - rh) * 1.33  # 75 to 95
        else:
            rh_score = 100.0

        # 3. Wind Speed Subscore (0 - 100)
        # Wind supplies oxygen and drives fire rate of spread and spotting
        if w <= 10.0:
            wind_score = w * 2.0  # 0 to 20
        elif w <= 25.0:
            wind_score = 20.0 + (w - 10.0) * 2.0  # 20 to 50
        elif w <= 45.0:
            wind_score = 50.0 + (w - 25.0) * 1.75  # 50 to 85
        else:
            wind_score = min(100.0, 85.0 + (w - 45.0) * 1.0)

        # 4. Precipitation & Moisture Deficit Subscore (0 - 100) [Inverted: rain dampens fuel]
        # Recent or impending precipitation significantly depresses fuel ignition
        effective_rain = p + (0.5 * fp)
        if effective_rain >= 15.0:
            moisture_score = 5.0
        elif effective_rain >= 5.0:
            moisture_score = 25.0 - (effective_rain - 5.0) * 2.0
        elif effective_rain >= 1.0:
            moisture_score = 55.0 - (effective_rain - 1.0) * 7.5
        elif effective_rain > 0.0:
            moisture_score = 75.0 - effective_rain * 20.0
        else:
            moisture_score = 90.0  # Complete dry spell

        # 5. Nearby Thermal Hotspot Activity Subscore (0 - 100)
        # Real satellite detections indicate confirmed thermal emissions / ongoing burning
        if nearby_hotspot_count == 0:
            hotspot_score = 10.0  # Background state
        elif nearby_hotspot_count <= 3:
            hotspot_score = 35.0 + nearby_hotspot_count * 5.0
        elif nearby_hotspot_count <= 15:
            hotspot_score = 50.0 + (nearby_hotspot_count - 3) * 2.5
        else:
            hotspot_score = min(100.0, 80.0 + math.log10(nearby_hotspot_count) * 10.0)

        # Boost if nearby FRP is intense (>100 MW)
        if nearby_total_frp > 100.0:
            hotspot_score = min(100.0, hotspot_score + 10.0)

        # 6. Combined Index with Synergistic Interaction
        # When RH is low and Temp is high and Wind is high, fire danger expands exponentially
        weather_base = (
            temp_score * 0.25 +
            rh_score * 0.30 +
            wind_score * 0.20 +
            moisture_score * 0.25
        )

        # Synergistic interaction factor (hot + dry + windy)
        interaction_boost = 0.0
        if temp_score > 60.0 and rh_score > 60.0 and wind_score > 50.0:
            interaction_boost = 12.0
        elif temp_score > 50.0 and rh_score > 50.0:
            interaction_boost = 6.0

        # Dampen if significant rain is actively falling
        if effective_rain > 10.0:
            weather_base *= 0.4
            interaction_boost = 0.0

        # Blend Weather Potential (65%) with Active Satellite Observations (35%)
        raw_score = (weather_base + interaction_boost) * 0.65 + (hotspot_score * 0.35)
        final_score = int(round(max(0.0, min(100.0, raw_score))))

        # Determine Alert Category
        contributing_factors: List[str] = []
        if final_score >= 65:
            alert_level = "RED"
            alert_title = "RED — HIGH ALERT"
            alert_class = "danger"
            color_hex = "#EF4444"
            summary_desc = (
                f"Elevated estimated environmental fire risk detected at {location_name}. "
                "Atmospheric dryness, thermal conditions, and/or active satellite-detected hotspots suggest high combustion potential."
            )
            recommendations = [
                "Intensify continuous satellite observation overpasses (NOAA-20/21, Suomi-NPP, MODIS).",
                "Monitor local air quality and potential smoke plume drift.",
                "Verify with official local forestry and civil protection emergency bulletins.",
                "Review immediate agricultural burning restrictions and dry-fuel buffers."
            ]
        elif final_score >= 35:
            alert_level = "ORANGE"
            alert_title = "ORANGE — MEDIUM ALERT"
            alert_class = "warning"
            color_hex = "#F97316"
            summary_desc = (
                f"Moderate estimated environmental fire risk at {location_name}. "
                "Weather variables indicate favorable drying conditions with moderate potential for ignition spread."
            )
            recommendations = [
                "Maintain periodic satellite monitoring across upcoming orbital cycles.",
                "Track upcoming humidity drops or increasing wind gusts in 24h forecast.",
                "Check regional agricultural and forest boundary activity."
            ]
        else:
            alert_level = "GREEN"
            alert_title = "GREEN — LOW RISK"
            alert_class = "success"
            color_hex = "#10B981"
            summary_desc = (
                f"Available meteorological and satellite evidence does not indicate elevated environmental fire risk at {location_name}."
            )
            recommendations = [
                "Routine observation schedule remains sufficient.",
                "Note: A green alert does not guarantee zero fire activity (small surface fires under dense canopy or heavy clouds may not be detectable by satellites)."
            ]

        # Factor contributions explanations
        if temp_score >= 60:
            contributing_factors.append(f"High ambient temperature ({t:.1f}°C) pre-heating fine vegetation.")
        if rh_score >= 60:
            contributing_factors.append(f"Low relative humidity ({rh:.0f}%) accelerating dead fuel desorption.")
        if wind_score >= 50:
            contributing_factors.append(f"Elevated wind speed ({w:.1f} km/h) facilitating flame spread and oxygen supply.")
        if moisture_score >= 80:
            contributing_factors.append("Prolonged absence of recent precipitation maintaining dry fuel beds.")
        if nearby_hotspot_count > 0:
            contributing_factors.append(f"{nearby_hotspot_count} active satellite hotspot(s) detected nearby ({nearby_total_frp:.1f} MW total FRP).")
        if not contributing_factors:
            contributing_factors.append("Moderate ambient temperatures, adequate relative humidity, and calm winds.")

        return {
            "score": final_score,
            "alert_level": alert_level,
            "alert_title": alert_title,
            "color_hex": color_hex,
            "location_name": location_name,
            "summary": summary_desc,
            "factors": {
                "temperature": {
                    "raw": t,
                    "unit": "°C",
                    "subscore": round(temp_score, 1),
                    "weight_pct": 25
                },
                "relative_humidity": {
                    "raw": rh,
                    "unit": "%",
                    "subscore": round(rh_score, 1),
                    "weight_pct": 30
                },
                "wind_speed": {
                    "raw": w,
                    "unit": "km/h",
                    "subscore": round(wind_score, 1),
                    "weight_pct": 20
                },
                "moisture_deficit": {
                    "raw_precip": p,
                    "unit": "mm",
                    "subscore": round(moisture_score, 1),
                    "weight_pct": 25
                },
                "thermal_activity": {
                    "nearby_hotspots": nearby_hotspot_count,
                    "total_frp_mw": nearby_total_frp,
                    "subscore": round(hotspot_score, 1)
                }
            },
            "contributing_factors": contributing_factors,
            "recommendations": recommendations,
            "limitations_disclaimer": (
                "DISCLAIMER & LIMITATIONS: The Environmental Fire-Risk Index (EFRI) is an advisory scientific indicator "
                "synthesized from satellite thermal radiometry and numerical weather reanalysis. It is NOT an official "
                "civil emergency warning or evacuation order. Satellite sensors (VIIRS/MODIS) cannot detect fires obscured by "
                "thick cloud cover, dense smoke, or under heavy closed-canopy forest, nor does this model replace ground-truth "
                "forestry inspection. Always defer to official regional civil defense and emergency authorities."
            )
        }

risk_engine = EnvironmentalFireRiskEngine()
