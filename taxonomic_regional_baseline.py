import math
import time
import requests
import pandas as pd


# ============================================================
# CONFIG
# ============================================================

SIGHTING_LAT = 18.4300
SIGHTING_LON = -77.1000

MAX_RADIUS_KM = 100
REQUEST_SIZE = 5000

OUTPUT_FILE = "taxonomic_regional_baseline.csv"

SPECIES = [
    "Sparisoma viride",
    "Acanthurus coeruleus",
    "Acanthurus bahianus",
    "Holacanthus ciliaris",
    "Pomacanthus paru",
    "Diodon hystrix",
    "Gymnothorax funebris",
    "Sphyraena barracuda",

    "Pterois volitans",
    "Pterois miles",

    "Amphiprion ocellaris",
    "Amphiprion clarkii",
    "Zebrasoma flavescens",
    "Paracanthurus hepatus",
    "Pterapogon kauderni",
    "Acanthurus japonicus",
    "Chaetodon auriga",
    "Chromis viridis",
    "Zanclus cornutus",
    "Siganus vulpinus",
]


# ============================================================
# DISTANCE
# ============================================================

def haversine_km(lat1, lon1, lat2, lon2):

    radius = 6371.0088

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    return (
        radius
        * 2
        * math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a)
        )
    )


# ============================================================
# GEOMETRY
# ============================================================

def create_bounding_box(lat, lon, radius_km):

    lat_delta = radius_km / 111.0

    lon_delta = (
        radius_km
        / (
            111.320
            * math.cos(
                math.radians(lat)
            )
        )
    )

    min_lat = lat - lat_delta
    max_lat = lat + lat_delta

    min_lon = lon - lon_delta
    max_lon = lon + lon_delta

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
# OBIS TAXON LOOKUP
# ============================================================

def find_taxon(scientific_name):

    url = (
        "https://api.obis.org/v3/"
        "taxon/complete/"
        + scientific_name
    )

    response = requests.get(
        url,
        timeout=60
    )

    response.raise_for_status()

    payload = response.json()

    if isinstance(payload, list):
        results = payload
    else:
        results = payload.get(
            "results",
            []
        )

    if not results:
        return None

    # Prefer exact scientific-name match.

    for result in results:

        name = result.get(
            "scientificName",
            ""
        )

        if (
            name.lower()
            == scientific_name.lower()
        ):
            return result

    return results[0]


def get_taxon_id(taxon):

    for field in [
        "aphiaID",
        "id",
        "taxonID",
        "speciesid",
    ]:

        value = taxon.get(field)

        if value is not None:
            return value

    return None


# ============================================================
# QUERY OCCURRENCES
# ============================================================

def query_occurrences(
    taxon_id,
    geometry
):

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

    return (
        payload.get("total", 0),
        payload.get("results", [])
    )


# ============================================================
# CLEAN OCCURRENCES
# ============================================================

def has_on_land(flags):

    if isinstance(flags, list):
        return "ON_LAND" in flags

    if isinstance(flags, str):
        return "ON_LAND" in flags

    return False


def clean_occurrences(records):

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    required = [
        "decimalLatitude",
        "decimalLongitude",
    ]

    for column in required:

        if column not in df.columns:
            return pd.DataFrame()

    df = df.dropna(
        subset=required
    ).copy()

    df["decimalLatitude"] = (
        pd.to_numeric(
            df["decimalLatitude"],
            errors="coerce"
        )
    )

    df["decimalLongitude"] = (
        pd.to_numeric(
            df["decimalLongitude"],
            errors="coerce"
        )
    )

    df = df.dropna(
        subset=required
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

    if "absence" in df.columns:

        df = df[
            df["absence"] != True
        ].copy()

    if "dropped" in df.columns:

        df = df[
            df["dropped"] != True
        ].copy()

    if "flags" in df.columns:

        df = df[
            ~df["flags"].apply(
                has_on_land
            )
        ].copy()

    if "occurrenceID" in df.columns:

        with_id = (
            df[
                df["occurrenceID"].notna()
            ]
            .drop_duplicates(
                subset=["occurrenceID"]
            )
        )

        without_id = df[
            df["occurrenceID"].isna()
        ]

        df = pd.concat(
            [
                with_id,
                without_id
            ],
            ignore_index=True
        )

    return df


# ============================================================
# ANALYSE OCCURRENCE SET
# ============================================================

def analyse_records(records):

    df = clean_occurrences(
        records
    )

    empty_result = {
        "10km": 0,
        "25km": 0,
        "50km": 0,
        "100km": 0,
        "nearest_km": None,
        "locations": 0,
    }

    if df.empty:
        return empty_result

    df["distance_km"] = df.apply(
        lambda row:
        haversine_km(
            SIGHTING_LAT,
            SIGHTING_LON,
            row["decimalLatitude"],
            row["decimalLongitude"],
        ),
        axis=1,
    )

    df = df[
        df["distance_km"]
        <= MAX_RADIUS_KM
    ].copy()

    if df.empty:
        return empty_result

    df["location_bucket"] = (
        df["decimalLatitude"]
        .round(3)
        .astype(str)
        + "_"
        + df["decimalLongitude"]
        .round(3)
        .astype(str)
    )

    return {
        "10km":
            int(
                (
                    df["distance_km"]
                    <= 10
                ).sum()
            ),

        "25km":
            int(
                (
                    df["distance_km"]
                    <= 25
                ).sum()
            ),

        "50km":
            int(
                (
                    df["distance_km"]
                    <= 50
                ).sum()
            ),

        "100km":
            int(
                (
                    df["distance_km"]
                    <= 100
                ).sum()
            ),

        "nearest_km":
            float(
                df["distance_km"].min()
            ),

        "locations":
            int(
                df["location_bucket"]
                .nunique()
            ),
    }


# ============================================================
# QUERY TAXON LEVEL
# ============================================================

def analyse_taxon_level(
    name,
    geometry,
    level
):

    if not name:

        return None

    print(
        f"  {level:<7}: {name}"
    )

    taxon = find_taxon(name)

    if taxon is None:

        print(
            "           taxon not found"
        )

        return None

    taxon_id = get_taxon_id(
        taxon
    )

    if taxon_id is None:

        print(
            "           no taxon ID"
        )

        return None

    total, records = (
        query_occurrences(
            taxon_id,
            geometry
        )
    )

    print(
        f"           "
        f"OBIS={total}, "
        f"returned={len(records)}"
    )

    result = analyse_records(
        records
    )

    result["taxon_id"] = (
        taxon_id
    )

    result["obis_total"] = (
        total
    )

    # Small pause so we're not hammering
    # the OBIS API.

    time.sleep(0.15)

    return result


# ============================================================
# MAIN
# ============================================================

geometry = create_bounding_box(
    SIGHTING_LAT,
    SIGHTING_LON,
    MAX_RADIUS_KM
)

print("=" * 80)
print("TAXONOMIC REGIONAL BASELINE")
print("=" * 80)

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


for scientific_name in SPECIES:

    print()
    print("=" * 80)
    print(scientific_name)
    print("=" * 80)

    species_taxon = find_taxon(
        scientific_name
    )

    if species_taxon is None:

        print(
            "Species could not be resolved."
        )

        continue


    # ========================================================
    # TAXONOMY
    # ========================================================

    genus_name = (
        species_taxon.get("genus")
    )

    family_name = (
        species_taxon.get("family")
    )

    print(
        f"Resolved genus:  "
        f"{genus_name}"
    )

    print(
        f"Resolved family: "
        f"{family_name}"
    )


    # ========================================================
    # THREE LEVELS
    # ========================================================

    species_result = (
        analyse_taxon_level(
            scientific_name,
            geometry,
            "SPECIES"
        )
    )

    genus_result = (
        analyse_taxon_level(
            genus_name,
            geometry,
            "GENUS"
        )
    )

    family_result = (
        analyse_taxon_level(
            family_name,
            geometry,
            "FAMILY"
        )
    )


    row = {
        "species":
            scientific_name,

        "genus":
            genus_name,

        "family":
            family_name,
    }


    # ========================================================
    # FLATTEN RESULTS
    # ========================================================

    for prefix, result in [
        (
            "species",
            species_result
        ),
        (
            "genus",
            genus_result
        ),
        (
            "family",
            family_result
        ),
    ]:

        if result is None:

            row[
                f"{prefix}_10km"
            ] = 0

            row[
                f"{prefix}_50km"
            ] = 0

            row[
                f"{prefix}_100km"
            ] = 0

            row[
                f"{prefix}_nearest_km"
            ] = None

            row[
                f"{prefix}_locations"
            ] = 0

        else:

            row[
                f"{prefix}_10km"
            ] = result["10km"]

            row[
                f"{prefix}_50km"
            ] = result["50km"]

            row[
                f"{prefix}_100km"
            ] = result["100km"]

            row[
                f"{prefix}_nearest_km"
            ] = result[
                "nearest_km"
            ]

            row[
                f"{prefix}_locations"
            ] = result[
                "locations"
            ]


    results.append(row)


# ============================================================
# RESULTS
# ============================================================

df = pd.DataFrame(
    results
)


display_columns = [
    "species",
    "genus",
    "family",

    "species_100km",
    "species_nearest_km",

    "genus_100km",
    "genus_nearest_km",

    "family_100km",
    "family_nearest_km",
]


print()
print("=" * 140)
print("TAXONOMIC COMPARISON")
print("=" * 140)


if not df.empty:

    print(
        df[
            display_columns
        ].to_string(
            index=False
        )
    )


df.to_csv(
    OUTPUT_FILE,
    index=False
)


print()
print(
    f"Saved to:\n"
    f"{OUTPUT_FILE}"
)