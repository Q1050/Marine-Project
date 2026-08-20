import math
import time
from functools import lru_cache

import pandas as pd
import requests

from geographic_utils import haversine_km


# ============================================================
# CONFIG
# ============================================================

OBIS_BASE_URL = "https://api.obis.org/v3"

DEFAULT_RADIUS_KM = 100
REQUEST_SIZE = 5000
REQUEST_TIMEOUT = 120


# ============================================================
# BOUNDING BOX
# ============================================================

def create_bounding_box(
    latitude,
    longitude,
    radius_km,
):

    lat_delta = (
        radius_km / 111.0
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

    min_lat = latitude - lat_delta
    max_lat = latitude + lat_delta

    min_lon = longitude - lon_delta
    max_lon = longitude + lon_delta

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
# REGIONAL EVIDENCE PROVIDER
# ============================================================

class RegionalEvidenceProvider:

    def __init__(
        self,
        radius_km=DEFAULT_RADIUS_KM,
    ):

        self.radius_km = radius_km

        self.session = (
            requests.Session()
        )


    # ========================================================
    # TAXON RESOLUTION
    # ========================================================

    @lru_cache(maxsize=512)
    def resolve_taxon(
        self,
        scientific_name,
    ):

        response = self.session.get(
            (
                f"{OBIS_BASE_URL}/"
                f"taxon/complete/"
                f"{scientific_name}"
            ),
            timeout=60,
        )

        response.raise_for_status()

        payload = response.json()

        # We already discovered that this
        # endpoint may return a list directly.

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


        # Prefer exact scientific-name match.

        for result in results:

            returned_name = (
                result.get(
                    "scientificName",
                    ""
                )
            )

            if (
                returned_name.lower()
                ==
                scientific_name.lower()
            ):

                return result


        return results[0]


    # ========================================================
    # TAXON ID
    # ========================================================

    @staticmethod
    def get_taxon_id(
        taxon
    ):

        if taxon is None:
            return None

        for field in [
            "aphiaID",
            "id",
            "taxonID",
            "speciesid",
        ]:

            value = taxon.get(
                field
            )

            if value is not None:
                return value

        return None


    # ========================================================
    # OBIS OCCURRENCE QUERY
    # ========================================================

    def query_occurrences(
        self,
        taxon_id,
        geometry,
        size=REQUEST_SIZE,
        offset=0,
    ):

        response = self.session.get(
            (
                f"{OBIS_BASE_URL}/"
                "occurrence"
            ),
            params={
                "taxonid":
                    taxon_id,

                "geometry":
                    geometry,

                "size":
                    size,

                "offset":
                    offset,
            },
            timeout=
                REQUEST_TIMEOUT,
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
            ),
        )


    # ========================================================
    # CLEAN DATA
    # ========================================================

    @staticmethod
    def _has_on_land(
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


    def clean_occurrences(
        self,
        records,
    ):

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(
            records
        )

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


        for column in required:

            df[column] = (
                pd.to_numeric(
                    df[column],
                    errors="coerce",
                )
            )


        df = df.dropna(
            subset=required
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


        if "absence" in df.columns:

            df = df[
                df["absence"]
                != True
            ].copy()


        if "dropped" in df.columns:

            df = df[
                df["dropped"]
                != True
            ].copy()


        if "flags" in df.columns:

            df = df[
                ~df[
                    "flags"
                ].apply(
                    self._has_on_land
                )
            ].copy()


        # Deduplicate by occurrence ID.

        if (
            "occurrenceID"
            in df.columns
        ):

            with_id = (
                df[
                    df[
                        "occurrenceID"
                    ].notna()
                ]
                .drop_duplicates(
                    subset=[
                        "occurrenceID"
                    ]
                )
            )

            without_id = (
                df[
                    df[
                        "occurrenceID"
                    ].isna()
                ]
            )

            df = pd.concat(
                [
                    with_id,
                    without_id,
                ],
                ignore_index=True,
            )


        return df


    # ========================================================
    # ANALYSE RECORDS
    # ========================================================

    def analyse_records(
        self,
        records,
        latitude,
        longitude,
    ):

        empty = {
            "records_10km": 0,
            "records_25km": 0,
            "records_50km": 0,
            "records_100km": 0,
            "nearest_km": None,
            "unique_locations": 0,
        }


        df = self.clean_occurrences(
            records
        )

        if df.empty:
            return empty


        df["distance_km"] = (
            df.apply(
                lambda row:
                    haversine_km(
                        latitude,
                        longitude,
                        row[
                            "decimalLatitude"
                        ],
                        row[
                            "decimalLongitude"
                        ],
                    ),
                axis=1,
            )
        )


        df = df[
            df["distance_km"]
            <= self.radius_km
        ].copy()


        if df.empty:
            return empty


        # Roughly 100 m location buckets.

        df[
            "location_bucket"
        ] = (
            df[
                "decimalLatitude"
            ]
            .round(3)
            .astype(str)
            +
            "_"
            +
            df[
                "decimalLongitude"
            ]
            .round(3)
            .astype(str)
        )


        return {

            "records_10km":
                int(
                    (
                        df["distance_km"]
                        <= 10
                    ).sum()
                ),

            "records_25km":
                int(
                    (
                        df["distance_km"]
                        <= 25
                    ).sum()
                ),

            "records_50km":
                int(
                    (
                        df["distance_km"]
                        <= 50
                    ).sum()
                ),

            "records_100km":
                int(
                    (
                        df["distance_km"]
                        <= 100
                    ).sum()
                ),

            "nearest_km":
                float(
                    df[
                        "distance_km"
                    ].min()
                ),

            "unique_locations":
                int(
                    df[
                        "location_bucket"
                    ].nunique()
                ),
        }


    # ========================================================
    # ANALYSE ONE TAXON
    # ========================================================

    def _get_taxon_evidence(
        self,
        taxon_name,
        latitude,
        longitude,
        geometry,
    ):

        if not taxon_name:

            return {
                "name": None,
                "taxon_id": None,
                "obis_total": 0,
                "records_10km": 0,
                "records_25km": 0,
                "records_50km": 0,
                "records_100km": 0,
                "nearest_km": None,
                "unique_locations": 0,
            }


        taxon = self.resolve_taxon(
            taxon_name
        )


        if taxon is None:

            return {
                "name": taxon_name,
                "taxon_id": None,
                "obis_total": 0,
                "records_10km": 0,
                "records_25km": 0,
                "records_50km": 0,
                "records_100km": 0,
                "nearest_km": None,
                "unique_locations": 0,
            }


        taxon_id = (
            self.get_taxon_id(
                taxon
            )
        )


        if taxon_id is None:

            return {
                "name": taxon_name,
                "taxon_id": None,
                "obis_total": 0,
                "records_10km": 0,
                "records_25km": 0,
                "records_50km": 0,
                "records_100km": 0,
                "nearest_km": None,
                "unique_locations": 0,
            }


        total, records = (
            self.query_occurrences(
                taxon_id,
                geometry,
            )
        )


        analysis = (
            self.analyse_records(
                records,
                latitude,
                longitude,
            )
        )


        return {
            "name":
                taxon_name,

            "taxon_id":
                taxon_id,

            "obis_total":
                int(total),

            **analysis,
        }


    # ========================================================
    # PUBLIC INTERFACE
    # ========================================================

    def get_evidence(
        self,
        species_name,
        latitude,
        longitude,
    ):

        latitude = float(
            latitude
        )

        longitude = float(
            longitude
        )


        if not (
            -90
            <= latitude
            <= 90
        ):

            raise ValueError(
                "Latitude must be "
                "between -90 and 90."
            )


        if not (
            -180
            <= longitude
            <= 180
        ):

            raise ValueError(
                "Longitude must be "
                "between -180 and 180."
            )


        species_taxon = (
            self.resolve_taxon(
                species_name
            )
        )


        if species_taxon is None:

            raise ValueError(
                f"Could not resolve taxon: "
                f"{species_name}"
            )


        genus_name = (
            species_taxon.get(
                "genus"
            )
        )

        family_name = (
            species_taxon.get(
                "family"
            )
        )


        geometry = (
            create_bounding_box(
                latitude,
                longitude,
                self.radius_km,
            )
        )


        species_evidence = (
            self._get_taxon_evidence(
                species_name,
                latitude,
                longitude,
                geometry,
            )
        )


        time.sleep(0.10)


        genus_evidence = (
            self._get_taxon_evidence(
                genus_name,
                latitude,
                longitude,
                geometry,
            )
        )


        time.sleep(0.10)


        family_evidence = (
            self._get_taxon_evidence(
                family_name,
                latitude,
                longitude,
                geometry,
            )
        )


        return {

            "species":
                species_evidence,

            "genus":
                genus_evidence,

            "family":
                family_evidence,
        }


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":

    import json


    provider = (
        RegionalEvidenceProvider()
    )


    evidence = (
        provider.get_evidence(
            species_name=
                "Pterois volitans",

            latitude=
                18.43,

            longitude=
                -77.10,
        )
    )


    print()
    print("=" * 80)
    print("DYNAMIC REGIONAL EVIDENCE")
    print("=" * 80)

    print(
        json.dumps(
            evidence,
            indent=2
        )
    )
