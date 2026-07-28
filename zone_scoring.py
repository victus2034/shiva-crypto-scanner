"""Transparent display-only quality score for confirmed wick zones."""


def score_wick_zone(zone, distance_pct, min_distance_pct, max_distance_pct):
    """Return a repeatable 4-10 score without changing alert eligibility."""
    if zone is None:
        return None

    score = 4
    wick_to_body = float(zone.get("wick_to_body", 0.0))
    wick_atr = float(zone.get("wick_atr", 0.0))
    departure_atr = float(zone.get("departure_atr", 0.0))
    touch_count = int(zone.get("touch_count", 0))

    if wick_to_body >= 2.5:
        score += 1
    if wick_atr >= 0.5:
        score += 1
    if departure_atr >= 1.5:
        score += 1
    if departure_atr >= 2.5:
        score += 1
    if touch_count == 0:
        score += 2
    elif touch_count == 1:
        score += 1

    midpoint = (min_distance_pct + max_distance_pct) / 2.0
    if distance_pct <= midpoint:
        score += 1

    return min(score, 10)
