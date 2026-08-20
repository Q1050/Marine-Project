import math
import requests
import pandas as pd


# ============================================================
# CONFIG
# ============================================================

SIGHTING_LAT = 18.4300
SIGHTING_LON = -77.1000

MAX_RADIUS_KM = 100

DISTANCE_BANDS = [
    10,
    25,
    50,
    100,
]

REQUEST_SIZE = 5000


SPECIES = [

    # ========================================================
    # CARIBBEAN / JAMAICA-REGIONAL SPECIES
    # ========================================================

    "Sparisoma viride",             # Stoplight parrotfish
    "Acanthurus coeruleus",         # Blue tang
    "Acanthurus bahianus",          # Ocean surgeonfish
    "Holacanthus ciliaris",         # Queen angelfish
    "Pomacanthus paru",             # French angelfish
    "Diodon hystrix",               # Spot-fin porcupinefish
    "Gymnothorax funebris",         # Green moray
    "Sphyraena barracuda",          # Great barracuda

    # ========================================================
    # ESTABLISHED INVASIVE
    # ========================================================

    "Pterois volitans",             # Red lionfish
    "Pterois miles",                # Devil firefish

    # ========================================================
    # NON-CARIBBEAN TEST SPECIES
    # ========================================================

    "Amphiprion ocellaris",         # Indo-Pacific clownfish
    "Amphiprion clarkii",           # Indo-Pacific clownfish
    "Zebrasoma flavescens",         # Yellow tang
    "Paracanthurus hepatus",        # Palette surgeonfish
    "Pterapogon kauderni",          # Banggai cardinalfish

    "Acanthurus japonicus",         # Indo-Pacific surgeonfish
    "Chaetodon auriga",             # Threadfin butterflyfish

    "Chromis viridis",              # Indo-Pacific damselfish
    "Zanclus cornutus",             # Moorish idol

    "Siganus vulpinus",             # Foxface rabbitfish
]


# ============================================================
# DISTANCE
# ============================================================

def haversine_km(
    lat1,
    lon1,
    lat2,
    lon2
):

    earth_radius = 6371.0088

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        +
        math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )

    return earth_radius * c


# ============================================================
# BOUNDING BOX
# ============================================================

def create_bounding_box(
    latitude,
    longitude,
    radius_km
):

    lat_delta = (
        radius_km
        / 111.0
    )

    lon_delta = (
        radius_km
        /
        (
            111.320
            * math.cos(
                math.radians(
                    latitude
                )
            )
        )
    )

    min_lat = (
        latitude
        - lat_delta
    )

    max_lat = (
        latitude
        + lat_delta
    )

    min_lon = (
        longitude
        - lon_delta
    )

    max_lon = (
        longitude
        + lon_delta
    )


    return (
        "POLYGON (("
        f"{min_lon} {min_lat}, "
        f"{min_lon} {max_lat}, "
        f"{max_lon} {max_lat}, "
        f"{max_lon} {min_lat}, "
        f"{min_lon} {min_lat}"
        "))"
    )


# ============================================================
# FIND TAXON
# ============================================================

def find_taxon(
    scientific_name
):

    print(
        f"Resolving taxon: "
        f"{scientific_name}"
    )

    url = (
        "https://api.obis.org/"
        "v3/taxon/complete/"
        + scientific_name
    )

    response = requests.get(
        url,
        timeout=60
    )

    response.raise_for_status()

    payload = response.json()


    if isinstance(
        payload,
        list
    ):

        results = payload

    else:

        results = payload.get(
            "results",
            []
        )


    if not results:

        return None


    for result in results:

        name = (
            result.get(
                "scientificName",
                ""
            )
        )

        if (
            name.lower()
            ==
            scientific_name.lower()
        ):

            return result


    return results[0]


# ============================================================
# EXTRACT TAXON ID
# ============================================================

def get_taxon_id(
    taxon
):

    possible_fields = [
        "aphiaID",
        "id",
        "taxonID",
        "speciesid",
    ]

    for field in possible_fields:

        value = taxon.get(
            field
        )

        if value is not None:

            return value

    return None


# ============================================================
# QUERY OBIS
# ============================================================

def get_local_occurrences(
    taxon_id,
    geometry
):

    response = requests.get(
        "https://api.obis.org/v3/occurrence",
        params={
            "taxonid":
                taxon_id,

            "geometry":
                geometry,

            "size":
                REQUEST_SIZE,
        },
        timeout=120,
    )

    response.raise_for_status()

    payload = response.json()

    return (
        payload.get(
            "total",
            0
        ),
        payload.get(
            "results",
            []
        )
    )


# ============================================================
# DATE PARSER
# ============================================================
def parse_obis_date(value):

    if pd.isna(value):
        return pd.NaT

    try:
        parsed = pd.to_datetime(
            value,
            errors="raise"
        )

        # Some OBIS dates contain timezone information.
        # Others are plain dates such as 2021-08-03.
        #
        # Force everything into UTC.

        if parsed.tzinfo is None:

            parsed = parsed.tz_localize(
                "UTC"
            )

        else:

            parsed = parsed.tz_convert(
                "UTC"
            )

        return parsed

    except Exception:

        return pd.NaT
# ============================================================
# ON LAND FLAG
# ============================================================

def has_on_land(
    flags
):

    if isinstance(
        flags,
        list
    ):

        return (
            "ON_LAND"
            in flags
        )


    if isinstance(
        flags,
        str
    ):

        return (
            "ON_LAND"
            in flags
        )


    return False


# ============================================================
# CLEAN ONE SPECIES
# ============================================================

def clean_occurrences(
    records
):

    if not records:

        return pd.DataFrame()


    df = pd.DataFrame(
        records
    )


    required_columns = [
        "decimalLatitude",
        "decimalLongitude",
    ]


    for column in required_columns:

        if (
            column
            not in df.columns
        ):

            return pd.DataFrame()


    df = df.dropna(
        subset=required_columns
    ).copy()


    df[
        "decimalLatitude"
    ] = pd.to_numeric(
        df[
            "decimalLatitude"
        ],
        errors="coerce"
    )


    df[
        "decimalLongitude"
    ] = pd.to_numeric(
        df[
            "decimalLongitude"
        ],
        errors="coerce"
    )


    df = df.dropna(
        subset=required_columns
    )


    df = df[
        df[
            "decimalLatitude"
        ].between(
            -90,
            90
        )
        &
        df[
            "decimalLongitude"
        ].between(
            -180,
            180
        )
    ].copy()


    if (
        "absence"
        in df.columns
    ):

        df = df[
            df[
                "absence"
            ] != True
        ].copy()


    if (
        "dropped"
        in df.columns
    ):

        df = df[
            df[
                "dropped"
            ] != True
        ].copy()


    if (
        "flags"
        in df.columns
    ):

        df = df[
            ~df[
                "flags"
            ].apply(
                has_on_land
            )
        ].copy()


    if (
        "occurrenceID"
        in df.columns
    ):

        with_id = df[
            df[
                "occurrenceID"
            ].notna()
        ].drop_duplicates(
            subset=[
                "occurrenceID"
            ]
        )

        without_id = df[
            df[
                "occurrenceID"
            ].isna()
        ]

        df = pd.concat(
            [
                with_id,
                without_id,
            ],
            ignore_index=True
        )


    return df


# ============================================================
# UNIQUE LOCATION BUCKET
# ============================================================

def add_location_bucket(
    df
):

    if df.empty:

        return df


    # Roughly groups very nearby records.
    #
    # 3 decimal places is about
    # ~100 meters in latitude.
    #
    # This is only for prototype
    # independence counting.

    df[
        "location_bucket"
    ] = (

        df[
            "decimalLatitude"
        ].round(3).astype(str)

        + "_"

        + df[
            "decimalLongitude"
        ].round(3).astype(str)

    )


    return df


# ============================================================
# ANALYSE SPECIES
# ============================================================

def analyse_species(
    scientific_name,
    geometry
):

    print()
    print("=" * 70)
    print(scientific_name)
    print("=" * 70)


    taxon = find_taxon(
        scientific_name
    )


    if taxon is None:

        print(
            "Taxon not found."
        )

        return None


    taxon_id = get_taxon_id(
        taxon
    )


    if taxon_id is None:

        print(
            "Could not resolve "
            "OBIS taxon ID."
        )

        return None


    print(
        f"Taxon ID: "
        f"{taxon_id}"
    )


    total_matching, records = (
        get_local_occurrences(
            taxon_id,
            geometry
        )
    )
    if total_matching == 0:
        print(
            "No regional OBIS records found."
        )

        return {
        "species": scientific_name,
        "taxon_id": taxon_id,
        "obis_total": 0,
        "clean_records": 0,
        "within_10km": 0,
        "within_25km": 0,
        "within_50km": 0,
        "within_100km": 0,
        "nearest_km": None,
        "past_1yr": 0,
        "past_5yr": 0,
        "unique_locations": 0,
        "unique_days": 0,
    }


    print(
        f"OBIS matching records: "
        f"{total_matching}"
    )


    print(
        f"Records returned: "
        f"{len(records)}"
    )


    if (
        total_matching
        > REQUEST_SIZE
    ):

        print(
            "WARNING: local result "
            "set was truncated."
        )


    df = clean_occurrences(
        records
    )


    if df.empty:

        return {
            "species":
                scientific_name,

            "taxon_id":
                taxon_id,

            "obis_total":
                total_matching,

            "clean_records":
                0,

            "within_10km":
                0,

            "within_25km":
                0,

            "within_50km":
                0,

            "within_100km":
                0,

            "nearest_km":
                None,

            "past_1yr":
                0,

            "past_5yr":
                0,

            "unique_locations":
                0,

            "unique_days":
                0,
        }


    # ========================================================
    # DISTANCE
    # ========================================================

    df[
        "distance_km"
    ] = df.apply(

        lambda row:
            haversine_km(

                SIGHTING_LAT,
                SIGHTING_LON,

                row[
                    "decimalLatitude"
                ],

                row[
                    "decimalLongitude"
                ]

            ),

        axis=1
    )


    df = df[
        df[
            "distance_km"
        ]
        <= MAX_RADIUS_KM
    ].copy()


    df = df.sort_values(
        "distance_km"
    )


    # ========================================================
    # DATES
    # ========================================================

    if (
        "eventDate"
        in df.columns
    ):

        df[
            "parsed_date"
        ] = df[
            "eventDate"
        ].apply(
            parse_obis_date
        )
        # Force the entire column into one
# consistent timezone-aware dtype.
        df["parsed_date"] = pd.to_datetime(
    df["parsed_date"],
    errors="coerce",
    utc=True
)
    else:

        df[
            "parsed_date"
        ] = pd.NaT


    now = pd.Timestamp.now(
        tz="UTC"
    )


    one_year_ago = (
        now
        - pd.DateOffset(
            years=1
        )
    )


    five_years_ago = (
        now
        - pd.DateOffset(
            years=5
        )
    )


    # ========================================================
    # LOCATION BUCKETS
    # ========================================================

    df = add_location_bucket(
        df
    )


    # ========================================================
    # DAY BUCKET
    # ========================================================

    df[
        "observation_day"
    ] = (
        df[
            "parsed_date"
        ]
        .dt
        .date
    )


    # ========================================================
    # DISTANCE COUNTS
    # ========================================================

    counts = {}

    for radius in (
        DISTANCE_BANDS
    ):

        counts[
            radius
        ] = int(

            (
                df[
                    "distance_km"
                ]
                <= radius
            ).sum()

        )


    # ========================================================
    # RECENCY
    # ========================================================

    dated = df[
        df[
            "parsed_date"
        ].notna()
    ]


    past_year = dated[
        dated[
            "parsed_date"
        ]
        >= one_year_ago
    ]


    past_five = dated[
        dated[
            "parsed_date"
        ]
        >= five_years_ago
    ]


    # ========================================================
    # UNIQUE COUNTS
    # ========================================================

    unique_locations = (
        df[
            "location_bucket"
        ]
        .nunique()
    )


    unique_days = (
        df[
            "observation_day"
        ]
        .dropna()
        .nunique()
    )


    nearest_distance = None

    if len(df):

        nearest_distance = float(
            df.iloc[0][
                "distance_km"
            ]
        )


    return {

        "species":
            scientific_name,

        "taxon_id":
            taxon_id,

        "obis_total":
            total_matching,

        "clean_records":
            len(df),

        "within_10km":
            counts[10],

        "within_25km":
            counts[25],

        "within_50km":
            counts[50],

        "within_100km":
            counts[100],

        "nearest_km":
            nearest_distance,

        "past_1yr":
            len(past_year),

        "past_5yr":
            len(past_five),

        "unique_locations":
            unique_locations,

        "unique_days":
            unique_days,

    }


# ============================================================
# MAIN
# ============================================================

geometry = create_bounding_box(
    SIGHTING_LAT,
    SIGHTING_LON,
    MAX_RADIUS_KM
)


print("=" * 70)
print("REGIONAL BASELINE COMPARISON")
print("=" * 70)

print(
    f"Location: "
    f"{SIGHTING_LAT}, "
    f"{SIGHTING_LON}"
)

print(
    f"Radius: "
    f"{MAX_RADIUS_KM} km"
)


results = []


for species in SPECIES:

    result = analyse_species(
        species,
        geometry
    )

    if result is not None:

        results.append(
            result
        )


# ============================================================
# TABLE
# ============================================================

results_df = pd.DataFrame(
    results
)


print()
print("=" * 110)
print("COMPARISON TABLE")
print("=" * 110)


if results_df.empty:

    print(
        "No results."
    )

else:

    display_columns = [
        "species",
        "within_10km",
        "within_25km",
        "within_50km",
        "within_100km",
        "nearest_km",
        "past_1yr",
        "past_5yr",
        "unique_locations",
        "unique_days",
    ]


    print(
        results_df[
            display_columns
        ]
        .to_string(
            index=False
        )
    )


# ============================================================
# SAVE
# ============================================================

OUTPUT_FILE = (
    "regional_baseline_comparison.csv"
)


results_df.to_csv(
    OUTPUT_FILE,
    index=False
)


print()
print(
    f"Saved to:\n"
    f"{OUTPUT_FILE}"
)