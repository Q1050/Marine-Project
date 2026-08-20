import math
import requests
import pandas as pd


# ============================================================
# CONFIG
# ============================================================

SCIENTIFIC_NAME = "Pterois volitans"
TAXON_ID = 159559

# Temporary Jamaica test point
SIGHTING_LAT = 18.1096
SIGHTING_LON = -77.2975

MAX_RADIUS_KM = 100

DISTANCE_BANDS = [
    10,
    25,
    50,
    100,
]

REQUEST_SIZE = 5000


# ============================================================
# HAVERSINE DISTANCE
# ============================================================

def haversine_km(lat1, lon1, lat2, lon2):

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
# CREATE BOUNDING BOX
# ============================================================

def create_bounding_box(
    latitude,
    longitude,
    radius_km
):

    # Approximate latitude conversion.
    lat_delta = radius_km / 111.0

    # Longitude distance changes with latitude.
    lon_delta = (
        radius_km
        /
        (
            111.320
            * math.cos(
                math.radians(latitude)
            )
        )
    )

    min_lat = latitude - lat_delta
    max_lat = latitude + lat_delta

    min_lon = longitude - lon_delta
    max_lon = longitude + lon_delta

    # WKT uses:
    #
    # longitude latitude
    #
    # NOT latitude longitude.

    geometry = (
        f"POLYGON (("
        f"{min_lon} {min_lat}, "
        f"{min_lon} {max_lat}, "
        f"{max_lon} {max_lat}, "
        f"{max_lon} {min_lat}, "
        f"{min_lon} {min_lat}"
        f"))"
    )

    return geometry


# ============================================================
# QUERY OBIS
# ============================================================

def get_local_occurrences(
    taxon_id,
    geometry
):

    print("Querying OBIS...")

    response = requests.get(
        "https://api.obis.org/v3/occurrence",
        params={
            "taxonid": taxon_id,
            "geometry": geometry,
            "size": REQUEST_SIZE,
        },
        timeout=120,
    )

    response.raise_for_status()

    payload = response.json()

    print(
        f"OBIS total matching records: "
        f"{payload.get('total')}"
    )

    records = payload.get(
        "results",
        []
    )

    print(
        f"Records returned: "
        f"{len(records)}"
    )

    return records


# ============================================================
# BUILD GEOGRAPHY
# ============================================================

geometry = create_bounding_box(
    SIGHTING_LAT,
    SIGHTING_LON,
    MAX_RADIUS_KM,
)


print("=" * 70)
print("OBIS REGIONAL BASELINE")
print("=" * 70)

print(
    f"Species: {SCIENTIFIC_NAME}"
)

print(
    f"Sighting: "
    f"{SIGHTING_LAT}, "
    f"{SIGHTING_LON}"
)

print(
    f"\nQuery geometry:\n"
    f"{geometry}"
)


# ============================================================
# DOWNLOAD LOCAL DATA
# ============================================================

records = get_local_occurrences(
    TAXON_ID,
    geometry,
)


if not records:

    print()
    print(
        "No OBIS occurrence records "
        "were found in the search region."
    )

    raise SystemExit()


df = pd.DataFrame(
    records
)


# ============================================================
# COORDINATE CLEANING
# ============================================================

required_columns = [
    "decimalLatitude",
    "decimalLongitude",
]


df = df.dropna(
    subset=required_columns
).copy()


df["decimalLatitude"] = pd.to_numeric(
    df["decimalLatitude"],
    errors="coerce",
)

df["decimalLongitude"] = pd.to_numeric(
    df["decimalLongitude"],
    errors="coerce",
)


df = df.dropna(
    subset=required_columns
)


df = df[
    df["decimalLatitude"].between(
        -90,
        90
    )
    &
    df["decimalLongitude"].between(
        -180,
        180
    )
].copy()


# ============================================================
# REMOVE ABSENCE
# ============================================================

if "absence" in df.columns:

    df = df[
        df["absence"] != True
    ].copy()


# ============================================================
# REMOVE DROPPED
# ============================================================

if "dropped" in df.columns:

    df = df[
        df["dropped"] != True
    ].copy()


# ============================================================
# REMOVE ON_LAND
# ============================================================

if "flags" in df.columns:

    def has_on_land(flags):

        if isinstance(flags, list):
            return "ON_LAND" in flags

        if isinstance(flags, str):
            return "ON_LAND" in flags

        return False


    df = df[
        ~df["flags"].apply(
            has_on_land
        )
    ].copy()


# ============================================================
# DEDUPLICATE
# ============================================================

if "occurrenceID" in df.columns:

    with_id = df[
        df["occurrenceID"].notna()
    ].drop_duplicates(
        subset=["occurrenceID"]
    )

    without_id = df[
        df["occurrenceID"].isna()
    ]

    df = pd.concat(
        [
            with_id,
            without_id,
        ],
        ignore_index=True,
    )


print(
    f"\nClean records: "
    f"{len(df)}"
)


# ============================================================
# EXACT DISTANCES
# ============================================================

df["distance_km"] = df.apply(

    lambda row: haversine_km(

        SIGHTING_LAT,
        SIGHTING_LON,

        row[
            "decimalLatitude"
        ],

        row[
            "decimalLongitude"
        ],

    ),

    axis=1,
)


# Bounding box includes corners farther
# than 100 km from the center.
#
# Remove those now using exact distance.

df = df[
    df["distance_km"]
    <= MAX_RADIUS_KM
].copy()


df = df.sort_values(
    "distance_km"
).reset_index(
    drop=True
)


# ============================================================
# DATES
# ============================================================

def parse_obis_date(value):

    if pd.isna(value):
        return pd.NaT

    try:
        return pd.to_datetime(
            value,
            errors="raise",
            utc=True
        )

    except Exception:
        return pd.NaT


if "eventDate" in df.columns:

    df["parsed_date"] = (
        df["eventDate"]
        .apply(parse_obis_date)
    )

else:

    df["parsed_date"] = pd.NaT


# Debug date parsing
print()
print("DATE PARSING CHECK")
print("-" * 40)

print(
    df[
        [
            "eventDate",
            "parsed_date"
        ]
    ]
    .head(15)
    .to_string(index=False)
)


print(
    f"\nSuccessfully parsed: "
    f"{df['parsed_date'].notna().sum()}"
    f"/{len(df)}"
)


now = pd.Timestamp.now(
    tz="UTC"
)

one_year_ago = (
    now
    - pd.DateOffset(years=1)
)

five_years_ago = (
    now
    - pd.DateOffset(years=5)
)

# ============================================================
# DISTANCE COUNTS
# ============================================================

distance_counts = {}


for radius in DISTANCE_BANDS:

    distance_counts[radius] = int(

        (
            df["distance_km"]
            <= radius
        ).sum()

    )


# ============================================================
# RECENCY
# ============================================================

dated = df[
    df["parsed_date"].notna()
].copy()


past_year = dated[
    dated["parsed_date"]
    >= one_year_ago
]


past_five_years = dated[
    dated["parsed_date"]
    >= five_years_ago
]


older_than_five = dated[
    dated["parsed_date"]
    < five_years_ago
]


# ============================================================
# SUMMARY
# ============================================================

nearest_distance = None

if len(df):

    nearest_distance = (
        df.iloc[0][
            "distance_km"
        ]
    )


earliest = (
    dated["parsed_date"].min()
    if len(dated)
    else pd.NaT
)


latest = (
    dated["parsed_date"].max()
    if len(dated)
    else pd.NaT
)


# ============================================================
# OUTPUT
# ============================================================

print()
print("=" * 70)
print("REGIONAL OCCURRENCE PROFILE")
print("=" * 70)

print(
    f"Species: "
    f"{SCIENTIFIC_NAME}"
)

print(
    f"Sighting: "
    f"{SIGHTING_LAT}, "
    f"{SIGHTING_LON}"
)

print(
    f"\nClean records within "
    f"{MAX_RADIUS_KM} km: "
    f"{len(df)}"
)


print()
print("DISTANCE EVIDENCE")
print("-" * 40)


for radius in DISTANCE_BANDS:

    print(
        f"Within {radius:>3} km: "
        f"{distance_counts[radius]}"
    )


if nearest_distance is not None:

    print(
        f"\nNearest record: "
        f"{nearest_distance:.2f} km"
    )


print()
print("RECENCY")
print("-" * 40)

print(
    f"Past 1 year: "
    f"{len(past_year)}"
)

print(
    f"Past 5 years: "
    f"{len(past_five_years)}"
)

print(
    f"Older than 5 years: "
    f"{len(older_than_five)}"
)

print(
    f"Without usable date: "
    f"{len(df) - len(dated)}"
)

print(
    f"\nEarliest: {earliest}"
)

print(
    f"Latest:   {latest}"
)


# ============================================================
# NEAREST RECORDS
# ============================================================

print()
print("=" * 70)
print("10 NEAREST CLEAN RECORDS")
print("=" * 70)


columns = [
    "scientificName",
    "decimalLatitude",
    "decimalLongitude",
    "distance_km",
    "eventDate",
    "basisOfRecord",
    "datasetName",
]


existing_columns = [
    column
    for column in columns
    if column in df.columns
]


if len(df):

    print(
        df[
            existing_columns
        ]
        .head(10)
        .to_string(
            index=False
        )
    )

else:

    print(
        "No records within exact "
        "100 km radius."
    )