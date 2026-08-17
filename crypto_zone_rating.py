from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


MODEL_PATH = Path(__file__).with_name("crypto_zone_rating_30m.joblib")
RATING_LABELS = {
    "A": "best tested",
    "B": "mixed",
    "C": "weak",
}
def rated_crypto_symbols() -> set[str]:
    """Symbols the loaded model bundle actually validates.

    Derived from the bundle itself (the single source of truth used by
    is_rating_eligible) rather than a hand-maintained list, which could
    silently drift out of sync with what the model really supports.
    """
    try:
        bundle = load_rating_bundle()
    except Exception:
        return set()
    return {str(value).upper() for value in bundle.get("validated_symbols", [])}


@lru_cache(maxsize=1)
def load_rating_bundle():
    return joblib.load(MODEL_PATH)


def is_rating_eligible(symbol, timeframe):
    if timeframe != "30m":
        return False
    try:
        bundle = load_rating_bundle()
    except Exception:
        return False
    support = bundle.get("validation_support", {})
    if support.get("verdict") != "SUPPORTED":
        return False
    validated_symbols = {
        str(value).upper() for value in bundle.get("validated_symbols", [])
    }
    return symbol.upper() in validated_symbols


def rate_crypto_zone(
    df,
    symbol,
    timeframe,
    zone_type,
    zone,
    distance_pct,
    swing_length=10,
):
    if zone is None or not is_rating_eligible(symbol, timeframe):
        return None

    try:
        bundle = load_rating_bundle()
        features = build_rating_features(
            df,
            zone_type,
            zone,
            distance_pct,
            swing_length,
        )
        columns = bundle["feature_columns"]
        feature_frame = pd.DataFrame(
            [[features[column] for column in columns]],
            columns=columns,
        )
        probability = float(
            bundle["model"].predict_proba(feature_frame)[0, 1]
        )
        reference = bundle.get("score_reference", [])
        if reference:
            percentile = np.searchsorted(
                np.asarray(reference, dtype=float),
                probability,
                side="right",
            ) / len(reference) * 100.0
            score = int(np.clip(np.ceil(percentile / 10.0), 1, 10))
        else:
            rating = score_to_rating(probability, bundle["thresholds"])
            score = {"A": 9, "B": 6, "C": 3}[rating]
        return {
            "score": score,
            "model_probability": probability,
        }
    except Exception as error:
        print(f"{symbol} zone rating unavailable: {error}")
        return None


def build_rating_features(
    df,
    zone_type,
    zone,
    distance_pct,
    swing_length=10,
):
    frame = df.reset_index(drop=True).copy()
    open_ = frame["open"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    index = len(frame) - 1
    pivot_index = int(zone.get("pivot_idx", zone["created_idx"]))
    confirmation_index = min(int(zone.get("created_idx", pivot_index + swing_length)), index)
    direction = 1.0 if zone_type == "demand" else -1.0
    atr_value = float(zone["atr"])
    if atr_value <= 0 or np.isnan(atr_value):
        raise ValueError("zone ATR is missing")

    ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
    ema50 = close.ewm(span=50, adjust=False, min_periods=50).mean()
    ema200 = close.ewm(span=200, adjust=False, min_periods=200).mean()
    rsi14 = _rsi(close, 14)
    adx14, plus_di, minus_di = _adx(frame, 14)
    volume_ratio20 = (
        volume
        / volume.rolling(20, min_periods=5).mean().replace(0, np.nan)
    )
    return_vol20 = (
        close.pct_change().rolling(20, min_periods=10).std() * 100.0
    )

    proximal = float(
        zone["top"] if zone_type == "demand" else zone["bottom"]
    )
    departure = _departure_strength(
        high,
        low,
        confirmation_index,
        index,
        proximal,
        direction,
    )
    current_gap = direction * (
        float(close.iloc[index]) - proximal
    ) / atr_value
    candle_range = float(high.iloc[index] - low.iloc[index])
    pivot_range = float(high.iloc[pivot_index] - low.iloc[pivot_index])
    pivot_body = abs(
        float(close.iloc[pivot_index] - open_.iloc[pivot_index])
    )
    pivot_wick = _aligned_pivot_wick(
        open_,
        high,
        low,
        close,
        pivot_index,
        direction,
    )
    timestamp = _candle_timestamp(frame, index)
    local = timestamp.tz_convert("Asia/Kolkata")
    hour = local.hour + local.minute / 60.0

    return {
        "side_long": int(direction == 1.0),
        "distance_pct": float(distance_pct),
        "distance_atr": (
            float(distance_pct)
            / 100.0
            * float(close.iloc[index])
            / atr_value
        ),
        "atr_pct": atr_value / float(close.iloc[index]) * 100.0,
        "touches_before_alert": int(zone.get("touch_count", 0)),
        "max_touch_streak_before_alert": int(
            zone.get("max_touch_streak", 0)
        ),
        "zone_age_bars": index - confirmation_index,
        "pivot_age_bars": index - pivot_index,
        "departure_strength_atr": departure / atr_value,
        "current_gap_atr": current_gap,
        "retracement_atr": departure / atr_value - current_gap,
        "pivot_wick_ratio": (
            pivot_wick / pivot_range if pivot_range > 0 else 0.0
        ),
        "pivot_body_atr": pivot_body / atr_value,
        "pivot_range_atr": pivot_range / atr_value,
        "ema20_gap_atr": _aligned_gap(
            close, ema20, index, direction, atr_value
        ),
        "ema50_gap_atr": _aligned_gap(
            close, ema50, index, direction, atr_value
        ),
        "ema200_gap_atr": _aligned_gap(
            close, ema200, index, direction, atr_value
        ),
        "ema20_slope5_atr": _aligned_slope(
            ema20, index, 5, direction, atr_value
        ),
        "ema50_slope5_atr": _aligned_slope(
            ema50, index, 5, direction, atr_value
        ),
        "momentum3_atr": _aligned_momentum(
            close, index, 3, direction, atr_value
        ),
        "momentum12_atr": _aligned_momentum(
            close, index, 12, direction, atr_value
        ),
        "rsi_aligned": direction * (float(rsi14.iloc[index]) - 50.0),
        "adx14": float(adx14.iloc[index]),
        "di_alignment": direction
        * float(plus_di.iloc[index] - minus_di.iloc[index]),
        "volume_ratio20": float(volume_ratio20.iloc[index]),
        "return_vol20_pct": float(return_vol20.iloc[index]),
        "alert_body_aligned_atr": direction
        * float(close.iloc[index] - open_.iloc[index])
        / atr_value,
        "alert_close_location_aligned": _aligned_close_location(
            high,
            low,
            close,
            index,
            direction,
            candle_range,
        ),
        "hour_sin": np.sin(2.0 * np.pi * hour / 24.0),
        "hour_cos": np.cos(2.0 * np.pi * hour / 24.0),
        "weekday_sin": np.sin(
            2.0 * np.pi * timestamp.weekday() / 7.0
        ),
        "weekday_cos": np.cos(
            2.0 * np.pi * timestamp.weekday() / 7.0
        ),
    }


def score_to_rating(score, thresholds):
    if score >= thresholds["A"]:
        return "A"
    if score >= thresholds["B"]:
        return "B"
    return "C"


def _candle_timestamp(frame, index):
    value = frame["time"].iloc[index]
    if isinstance(value, (int, float, np.integer, np.floating)):
        return pd.to_datetime(value, unit="ms", utc=True)
    return pd.to_datetime(value, utc=True)


def _true_range(frame):
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    return pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _rsi(close, period):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    loss = (-delta.clip(upper=0)).ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    relative_strength = gain / loss.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _adx(frame, period):
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where(
            (up_move > down_move) & (up_move > 0),
            up_move,
            0.0,
        ),
        index=frame.index,
    )
    minus_dm = pd.Series(
        np.where(
            (down_move > up_move) & (down_move > 0),
            down_move,
            0.0,
        ),
        index=frame.index,
    )
    atr14 = _true_range(frame).ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    plus_di = (
        100.0
        * plus_dm.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        ).mean()
        / atr14.replace(0, np.nan)
    )
    minus_di = (
        100.0
        * minus_dm.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        ).mean()
        / atr14.replace(0, np.nan)
    )
    dx = (
        100.0
        * (plus_di - minus_di).abs()
        / (plus_di + minus_di).replace(0, np.nan)
    )
    adx = dx.ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    return adx, plus_di, minus_di


def _departure_strength(
    high,
    low,
    start,
    end,
    proximal,
    direction,
):
    if direction == 1.0:
        return max(0.0, float(high.iloc[start : end + 1].max()) - proximal)
    return max(0.0, proximal - float(low.iloc[start : end + 1].min()))


def _aligned_pivot_wick(
    open_,
    high,
    low,
    close,
    index,
    direction,
):
    if direction == 1.0:
        return max(
            0.0,
            min(float(open_.iloc[index]), float(close.iloc[index]))
            - float(low.iloc[index]),
        )
    return max(
        0.0,
        float(high.iloc[index])
        - max(float(open_.iloc[index]), float(close.iloc[index])),
    )


def _aligned_gap(
    close,
    average,
    index,
    direction,
    atr_value,
):
    return direction * (
        float(close.iloc[index]) - float(average.iloc[index])
    ) / atr_value


def _aligned_slope(
    average,
    index,
    lookback,
    direction,
    atr_value,
):
    if index < lookback:
        return np.nan
    return direction * (
        float(average.iloc[index])
        - float(average.iloc[index - lookback])
    ) / atr_value


def _aligned_momentum(
    close,
    index,
    lookback,
    direction,
    atr_value,
):
    if index < lookback:
        return np.nan
    return direction * (
        float(close.iloc[index])
        - float(close.iloc[index - lookback])
    ) / atr_value


def _aligned_close_location(
    high,
    low,
    close,
    index,
    direction,
    candle_range,
):
    if candle_range <= 0:
        return 0.5
    if direction == 1.0:
        return (
            float(close.iloc[index]) - float(low.iloc[index])
        ) / candle_range
    return (
        float(high.iloc[index]) - float(close.iloc[index])
    ) / candle_range
