import pandas as pd
import numpy as np


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = "regional_baseline_comparison.csv"

OUTPUT_FILE = "regional_familiarity_scores.csv"


# ============================================================
# SCORING FUNCTIONS
# ============================================================

def distance_score(nearest_km):
    """
    Measures how geographically close the nearest
    historical occurrence is.

    Returns 0.0 - 1.0.
    """

    if pd.isna(nearest_km):
        return 0.0

    if nearest_km <= 10:
        return 1.0

    if nearest_km <= 25:
        return 0.85

    if nearest_km <= 50:
        return 0.60

    if nearest_km <= 100:
        return 0.30

    return 0.0


def density_score(row):
    """
    Measures occurrence density across several
    geographic scales.

    More weight is given to nearby observations.
    """

    score_10 = min(
        row["within_10km"] / 10,
        1.0
    )

    score_25 = min(
        row["within_25km"] / 20,
        1.0
    )

    score_50 = min(
        row["within_50km"] / 40,
        1.0
    )

    score_100 = min(
        row["within_100km"] / 80,
        1.0
    )

    return (
        score_10 * 0.40
        + score_25 * 0.30
        + score_50 * 0.20
        + score_100 * 0.10
    )


def recency_score(row):
    """
    Measures whether the species has recent
    occurrence evidence.
    """

    recent_1yr = min(
        row["past_1yr"] / 5,
        1.0
    )

    recent_5yr = min(
        row["past_5yr"] / 20,
        1.0
    )

    return (
        recent_1yr * 0.65
        + recent_5yr * 0.35
    )


def independence_score(row):
    """
    Reduces the influence of many observations
    coming from the same place or same survey day.
    """

    locations = min(
        row["unique_locations"] / 20,
        1.0
    )

    days = min(
        row["unique_days"] / 20,
        1.0
    )

    return (
        locations * 0.60
        + days * 0.40
    )


# ============================================================
# LOAD DATA
# ============================================================

df = pd.read_csv(
    INPUT_FILE
)


print("=" * 75)
print("REGIONAL FAMILIARITY SCORING")
print("=" * 75)

print(
    f"Species loaded: {len(df)}"
)


# ============================================================
# COMPONENT SCORES
# ============================================================

df["distance_score"] = (
    df["nearest_km"]
    .apply(distance_score)
)


df["density_score"] = df.apply(
    density_score,
    axis=1
)


df["recency_score"] = df.apply(
    recency_score,
    axis=1
)


df["independence_score"] = df.apply(
    independence_score,
    axis=1
)


# ============================================================
# FINAL FAMILIARITY SCORE
# ============================================================
#
# These weights are intentionally provisional.
#
# We are NOT claiming they are scientifically calibrated.
# We are creating a baseline that we can test and later
# replace/calibrate using a larger dataset.
#
# ============================================================

df["familiarity_score"] = (

    df["distance_score"] * 0.30

    + df["density_score"] * 0.30

    + df["recency_score"] * 0.25

    + df["independence_score"] * 0.15
)


# ============================================================
# ANOMALY SCORE
# ============================================================

df["anomaly_score"] = (
    1.0
    - df["familiarity_score"]
)


# ============================================================
# TEMPORARY INTERPRETATION
# ============================================================
#
# Again: these thresholds are experimental.
#
# They are useful for testing behavior, NOT yet
# scientifically validated classification thresholds.
#
# ============================================================

def interpret(score):

    if score >= 0.75:
        return "STRONG_REGIONAL_EVIDENCE"

    if score >= 0.50:
        return "MODERATE_REGIONAL_EVIDENCE"

    if score >= 0.25:
        return "WEAK_REGIONAL_EVIDENCE"

    return "REGIONALLY_UNUSUAL"


df["regional_status"] = (
    df["familiarity_score"]
    .apply(interpret)
)


# ============================================================
# ROUND DISPLAY VALUES
# ============================================================

score_columns = [
    "distance_score",
    "density_score",
    "recency_score",
    "independence_score",
    "familiarity_score",
    "anomaly_score",
]


df[
    score_columns
] = df[
    score_columns
].round(4)


# ============================================================
# OUTPUT
# ============================================================

display_columns = [
    "species",
    "distance_score",
    "density_score",
    "recency_score",
    "independence_score",
    "familiarity_score",
    "anomaly_score",
    "regional_status",
]


print()
print("=" * 110)
print("RESULTS")
print("=" * 110)

print(
    df[
        display_columns
    ]
    .sort_values(
        "familiarity_score",
        ascending=False
    )
    .to_string(
        index=False
    )
)


# ============================================================
# SAVE
# ============================================================

df.to_csv(
    OUTPUT_FILE,
    index=False
)


print()
print(
    f"Results saved to:\n"
    f"{OUTPUT_FILE}"
)