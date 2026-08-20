import pandas as pd
from dataclasses import dataclass
from typing import Optional


# ============================================================
# CONFIG
# ============================================================

REGIONAL_BASELINE_FILE = (
    "taxonomic_regional_baseline.csv"
)

# These come from our earlier open-set experiment.
VISION_SCORE_THRESHOLD = 0.805
VISION_MARGIN_THRESHOLD = 0.040


# ============================================================
# TEMPORARY ECOLOGICAL KNOWLEDGE
# ============================================================
#
# This is deliberately tiny.
#
# Later this should NOT be a hard-coded dictionary.
# It will become a proper species/region knowledge layer.
#
# For now we only need enough data to prove that:
#
# regional familiarity != ecological/native status
#
# ============================================================

ECOLOGICAL_STATUS_LEGACY_COMPAT = {

    "Pterois volitans": "INVASIVE",

    "Sparisoma viride": "NATIVE",

    "Acanthurus coeruleus": "NATIVE",

    "Acanthurus bahianus": "NATIVE",

    "Holacanthus ciliaris": "NATIVE",

    "Pomacanthus paru": "NATIVE",

    "Diodon hystrix": "NATIVE",

    "Gymnothorax funebris": "NATIVE",

    "Sphyraena barracuda": "NATIVE",
}


# ============================================================
# RESULT OBJECT
# ============================================================

@dataclass
class AnomalyResult:

    species: str

    decision: str

    priority: str

    vision_accepted: bool

    species_records: int

    genus_records: int

    family_records: int

    ecological_status: str

    reason: str


# ============================================================
# LOAD REGIONAL BASELINE
# ============================================================

regional_df = pd.read_csv(
    REGIONAL_BASELINE_FILE
)


# ============================================================
# HELPERS
# ============================================================

def safe_int(value):

    if pd.isna(value):
        return 0

    return int(value)


def get_regional_record(
    species_name
):

    matches = regional_df[
        regional_df["species"]
        .str.lower()
        ==
        species_name.lower()
    ]

    if matches.empty:
        return None

    return matches.iloc[0]


# ============================================================
# VISION ACCEPTANCE
# ============================================================

def vision_is_accepted(
    score: float,
    margin: float
):

    return (
        score >= VISION_SCORE_THRESHOLD
        and
        margin >= VISION_MARGIN_THRESHOLD
    )


# ============================================================
# REGIONAL PATTERN
# ============================================================

def determine_regional_pattern(
    species_records,
    genus_records,
    family_records
):

    # Exact species has regional evidence.

    if species_records > 0:

        return "SPECIES_PRESENT"


    # Exact species absent, but genus occurs locally.

    if (
        species_records == 0
        and genus_records > 0
    ):

        return "GENUS_PRESENT"


    # Species + genus absent,
    # but related family occurs locally.

    if (
        species_records == 0
        and genus_records == 0
        and family_records > 0
    ):

        return "FAMILY_PRESENT"


    # Entire branch absent from local baseline.

    return "NO_TAXONOMIC_EVIDENCE"


# ============================================================
# MAIN ENGINE
# ============================================================

def evaluate_observation(
    species_name: str,
    vision_score: float,
    vision_margin: float,
    ecological_status: str = "UNKNOWN",
    vision_accepted: bool = True,
    species_records: int = 0,
    genus_records: int = 0,
    family_records: int = 0,
):
    """Evaluate an observation's anomaly class.

    Ecological classification is jurisdiction-isolated and MUST be resolved
    upstream (see ``species_jurisdiction_ecology.resolve_ecological_status``).
    The anomaly engine does NOT consult any global ecological dictionary.

    The parameter ``ecological_status`` is the pre-resolved
    jurisdiction-specific ecological status. ``species_records``,
    ``genus_records``, and ``family_records`` are pre-aggregated regional
    evidence counts (jurisdiction-agnostic in their semantics).
    """

    # --------------------------------------------------------
    # STEP 1 — VISION
    # --------------------------------------------------------

    accepted = vision_is_accepted(
        vision_score,
        vision_margin
    )


    if not accepted:

        return AnomalyResult(

            species=species_name,

            decision=(
                "UNRESOLVED_IDENTIFICATION"
            ),

            priority="REVIEW",

            vision_accepted=False,

            species_records=0,
            genus_records=0,
            family_records=0,

            ecological_status="UNKNOWN",

            reason=(
                "Vision identification did not "
                "meet the open-set acceptance "
                "threshold."
            ),
        )


    # --------------------------------------------------------
    # STEP 2 — REGIONAL DATA
    # --------------------------------------------------------

    regional = get_regional_record(
        species_name
    )


    if regional is None:

        return AnomalyResult(

            species=species_name,

            decision="HIGH_PRIORITY_REVIEW",

            priority="HIGH",

            vision_accepted=True,

            species_records=0,
            genus_records=0,
            family_records=0,

            ecological_status="UNKNOWN",

            reason=(
                "Species was accepted by the "
                "vision layer but no regional "
                "baseline record is available "
                "for evaluation."
            ),
        )


    species_records = safe_int(
        regional[
            "species_100km"
        ]
    )

    genus_records = safe_int(
        regional[
            "genus_100km"
        ]
    )

    family_records = safe_int(
        regional[
            "family_100km"
        ]
    )


    # --------------------------------------------------------
    # STEP 3 — TAXONOMIC PATTERN
    # --------------------------------------------------------

    pattern = determine_regional_pattern(

        species_records,
        genus_records,
        family_records
    )


    # --------------------------------------------------------
    # STEP 4 — ECOLOGICAL STATUS (jurisdiction-isolated, pre-resolved)
    # --------------------------------------------------------
    #
    # The ecological_status argument is supplied by the caller after
    # resolving it via the SpeciesJurisdictionStatus registry. The
    # anomaly engine MUST NOT independently consult a global ecological
    # dictionary. Defaults to "UNKNOWN" if absent so that the engine
    # does not produce KNOWN_INVASIVE_RECORD without a registry-backed
    # jurisdiction-specific claim.


    # --------------------------------------------------------
    # STEP 5 — DECISION
    # --------------------------------------------------------

    if pattern == "SPECIES_PRESENT":

        if (
            ecological_status
            == "INVASIVE"
        ):

            return AnomalyResult(

                species=species_name,

                decision=(
                    "KNOWN_INVASIVE_RECORD"
                ),

                priority="MONITOR",

                vision_accepted=True,

                species_records=species_records,
                genus_records=genus_records,
                family_records=family_records,

                ecological_status=(
                    ecological_status
                ),

                reason=(
                    "Exact species has regional "
                    "occurrence evidence and is "
                    "marked invasive in the "
                    "ecological knowledge layer."
                ),
            )


        return AnomalyResult(

            species=species_name,

            decision=(
                "NORMAL_REGIONAL_RECORD"
            ),

            priority="LOW",

            vision_accepted=True,

            species_records=species_records,
            genus_records=genus_records,
            family_records=family_records,

            ecological_status=(
                ecological_status
            ),

            reason=(
                "Exact species has historical "
                "regional occurrence evidence."
            ),
        )


    if pattern == "GENUS_PRESENT":

        return AnomalyResult(

            species=species_name,

            decision=(
                "SPECIES_LEVEL_ANOMALY"
            ),

            priority="REVIEW",

            vision_accepted=True,

            species_records=species_records,
            genus_records=genus_records,
            family_records=family_records,

            ecological_status=(
                ecological_status
            ),

            reason=(
                "No exact-species occurrence "
                "evidence was found, but the "
                "genus is regionally represented."
            ),
        )


    if pattern == "FAMILY_PRESENT":

        return AnomalyResult(

            species=species_name,

            decision=(
                "TAXONOMIC_ANOMALY"
            ),

            priority="HIGH",

            vision_accepted=True,

            species_records=species_records,
            genus_records=genus_records,
            family_records=family_records,

            ecological_status=(
                ecological_status
            ),

            reason=(
                "Neither the exact species nor "
                "its genus has regional evidence, "
                "although members of the family "
                "occur regionally."
            ),
        )


    return AnomalyResult(

        species=species_name,

        decision=(
            "HIGH_PRIORITY_REVIEW"
        ),

        priority="HIGH",

        vision_accepted=True,

        species_records=species_records,
        genus_records=genus_records,
        family_records=family_records,

        ecological_status=(
            ecological_status
        ),

        reason=(
            "No regional occurrence evidence "
            "was found for the species, genus, "
            "or family."
        ),
    )


# ============================================================
# CONTROLLED TEST CASES
# ============================================================

TEST_CASES = [

    # Established invasive
    {
        "species":
            "Pterois volitans",

        "score": 0.91,
        "margin": 0.10,
    },


    # Exact species absent,
    # genus strongly represented.
    {
        "species":
            "Pterois miles",

        "score": 0.90,
        "margin": 0.08,
    },


    # Species + genus absent,
    # family represented.
    {
        "species":
            "Amphiprion ocellaris",

        "score": 0.92,
        "margin": 0.12,
    },


    # Entire taxonomic branch absent.
    {
        "species":
            "Zanclus cornutus",

        "score": 0.93,
        "margin": 0.14,
    },


    # Deliberately uncertain vision result.
    {
        "species":
            "Amphiprion ocellaris",

        "score": 0.79,
        "margin": 0.03,
    },
]


# ============================================================
# RUN TESTS
# ============================================================
if __name__ == "__main__":
 print("=" * 80)
 print("ANOMALY ENGINE TEST")
 print("=" * 80)


 for case in TEST_CASES:

    result = evaluate_observation(

        species_name=case["species"],

        vision_score=case["score"],

        vision_margin=case["margin"],
    )


    print()
    print("=" * 80)

    print(
        f"SPECIES: "
        f"{result.species}"
    )

    print(
        f"VISION ACCEPTED: "
        f"{result.vision_accepted}"
    )

    print(
        f"REGIONAL RECORDS: "
        f"species={result.species_records}, "
        f"genus={result.genus_records}, "
        f"family={result.family_records}"
    )

    print(
        f"ECOLOGICAL STATUS: "
        f"{result.ecological_status}"
    )

    print(
        f"DECISION: "
        f"{result.decision}"
    )

    print(
        f"PRIORITY: "
        f"{result.priority}"
    )

    print(
        f"REASON: "
        f"{result.reason}"
    )