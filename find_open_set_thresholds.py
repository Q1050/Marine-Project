import pandas as pd


# ============================================================
# CONFIG
# ============================================================

CSV_FILE = "open_set_scores.csv"


# ============================================================
# LOAD
# ============================================================

df = pd.read_csv(CSV_FILE)

known = df[
    df["group"] == "known"
].copy()

unknown = df[
    df["group"] == "unknown"
].copy()


print("=" * 75)
print("OPEN-SET THRESHOLD SEARCH")
print("=" * 75)

print(f"Known samples:   {len(known)}")
print(f"Unknown samples: {len(unknown)}")


# ============================================================
# SEARCH SPACE
# ============================================================

score_thresholds = [
    round(x / 1000, 3)
    for x in range(750, 901, 5)
]

margin_thresholds = [
    round(x / 1000, 3)
    for x in range(0, 101, 5)
]


results = []


# ============================================================
# TEST THRESHOLDS
# ============================================================

for score_threshold in score_thresholds:

    for margin_threshold in margin_thresholds:

        # Accept only when BOTH conditions are satisfied.

        known_accepted = (
            (known["top_score"] >= score_threshold)
            &
            (known["margin"] >= margin_threshold)
        )

        unknown_accepted = (
            (unknown["top_score"] >= score_threshold)
            &
            (unknown["margin"] >= margin_threshold)
        )


        known_acceptance_rate = (
            known_accepted.mean()
        )

        unknown_rejection_rate = (
            (~unknown_accepted).mean()
        )

        false_acceptance_rate = (
            unknown_accepted.mean()
        )


        # Balanced open-set performance.
        balanced_score = (
            known_acceptance_rate
            + unknown_rejection_rate
        ) / 2


        results.append({

            "score_threshold":
                score_threshold,

            "margin_threshold":
                margin_threshold,

            "known_acceptance":
                known_acceptance_rate,

            "unknown_rejection":
                unknown_rejection_rate,

            "false_acceptance":
                false_acceptance_rate,

            "balanced_score":
                balanced_score,
        })


# ============================================================
# RESULTS
# ============================================================

results_df = pd.DataFrame(results)


# ------------------------------------------------------------
# BEST BALANCED
# ------------------------------------------------------------

best_balanced = (
    results_df
    .sort_values(
        [
            "balanced_score",
            "false_acceptance",
        ],
        ascending=[
            False,
            True,
        ]
    )
    .head(15)
)


print()
print("=" * 75)
print("BEST BALANCED THRESHOLDS")
print("=" * 75)

print(
    best_balanced.to_string(
        index=False
    )
)


# ------------------------------------------------------------
# ZERO FALSE ACCEPTANCE
# ------------------------------------------------------------

zero_false_acceptance = (
    results_df[
        results_df[
            "false_acceptance"
        ] == 0
    ]
    .sort_values(
        "known_acceptance",
        ascending=False
    )
    .head(15)
)


print()
print("=" * 75)
print("ZERO FALSE-ACCEPTANCE OPTIONS")
print("=" * 75)

if zero_false_acceptance.empty:

    print(
        "No threshold combination "
        "achieved zero false acceptance."
    )

else:

    print(
        zero_false_acceptance.to_string(
            index=False
        )
    )


# ------------------------------------------------------------
# <= 2% FALSE ACCEPTANCE
# ------------------------------------------------------------

safe_options = (
    results_df[
        results_df[
            "false_acceptance"
        ] <= 0.02
    ]
    .sort_values(
        [
            "known_acceptance",
            "balanced_score",
        ],
        ascending=[
            False,
            False,
        ]
    )
    .head(15)
)


print()
print("=" * 75)
print("<= 2% FALSE-ACCEPTANCE OPTIONS")
print("=" * 75)

print(
    safe_options.to_string(
        index=False
    )
)

# ============================================================
# SAVE FULL SEARCH
# ============================================================

results_df.to_csv(
    "open_set_threshold_search.csv",
    index=False
)

print()
print(
    "Full threshold search saved to:"
)

print(
    "open_set_threshold_search.csv"
)