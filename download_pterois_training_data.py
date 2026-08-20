from pathlib import Path
import time

import pandas as pd
import requests


# ============================================================
# CONFIG
# ============================================================

SPECIES = {
    "pterois_volitans": "Pterois volitans",
    "pterois_miles": "Pterois miles",
}

IMAGES_PER_SPECIES = 100

OUTPUT_DIR = Path(
    "data/pterois_dataset/raw"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "MarineIntelligenceBuildathon/0.1"
    )
})


# ============================================================
# FIND TAXON
# ============================================================

def find_taxon(scientific_name):

    url = (
        "https://api.inaturalist.org/v1/taxa"
    )

    params = {
        "q": scientific_name,
        "rank": "species",
        "per_page": 20,
    }

    response = session.get(
        url,
        params=params,
        timeout=60,
    )

    response.raise_for_status()

    results = response.json().get(
        "results",
        []
    )

    for taxon in results:

        if (
            taxon.get(
                "name",
                ""
            ).lower()
            ==
            scientific_name.lower()
        ):

            return taxon

    return None


# ============================================================
# GET OBSERVATIONS
# ============================================================

def get_observations(
    taxon_id,
    page,
    per_page=100
):

    url = (
        "https://api.inaturalist.org/"
        "v1/observations"
    )

    params = {
        "taxon_id": taxon_id,

        # Higher-quality observations.
        "quality_grade": "research",

        # Require photographic evidence.
        "photos": "true",

        "per_page": per_page,

        "page": page,

        "order_by": "created_at",

        "order": "desc",
    }

    response = session.get(
        url,
        params=params,
        timeout=60,
    )

    if response.status_code == 429:

        print(
            "API rate limited. "
            "Waiting 60 seconds..."
        )

        time.sleep(60)

        return []

    response.raise_for_status()

    return response.json().get(
        "results",
        []
    )


# ============================================================
# PHOTO URL
# ============================================================

def get_photo_url(photo):

    url = photo.get("url")

    if not url:
        return None

    # Use large rather than tiny square thumbnails.
    return (
        url
        .replace(
            "/square.",
            "/large."
        )
        .replace(
            "/small.",
            "/large."
        )
        .replace(
            "/medium.",
            "/large."
        )
    )


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(
    url,
    destination,
    max_retries=3
):

    for attempt in range(
        1,
        max_retries + 1
    ):

        try:

            response = session.get(
                url,
                timeout=60,
            )

            if response.status_code == 429:

                wait_time = (
                    attempt * 30
                )

                print(
                    f"Rate limited. "
                    f"Waiting "
                    f"{wait_time}s..."
                )

                time.sleep(
                    wait_time
                )

                continue

            response.raise_for_status()

            destination.write_bytes(
                response.content
            )

            return True

        except requests.RequestException as exc:

            print(
                f"Download attempt "
                f"{attempt} failed: "
                f"{exc}"
            )

            time.sleep(
                attempt * 5
            )

    return False


# ============================================================
# MAIN DOWNLOAD PROCESS
# ============================================================

metadata = []


for (
    folder_name,
    scientific_name
) in SPECIES.items():

    print()
    print("=" * 70)
    print(scientific_name)
    print("=" * 70)

    taxon = find_taxon(
        scientific_name
    )

    if not taxon:

        print(
            "Taxon could not be found."
        )

        continue


    taxon_id = taxon["id"]

    print(
        f"Taxon ID: "
        f"{taxon_id}"
    )


    species_dir = (
        OUTPUT_DIR
        / folder_name
    )

    species_dir.mkdir(
        parents=True,
        exist_ok=True
    )


    downloaded = 0
    page = 1

    used_photo_ids = set()
    used_observation_ids = set()


    while (
        downloaded
        < IMAGES_PER_SPECIES
    ):

        print()
        print(
            f"Fetching observation "
            f"page {page}..."
        )


        observations = (
            get_observations(
                taxon_id,
                page
            )
        )


        if not observations:

            print(
                "No additional "
                "observations found."
            )

            break


        for observation in observations:

            if (
                downloaded
                >= IMAGES_PER_SPECIES
            ):
                break


            observation_id = (
                observation.get("id")
            )


            # One image per independent
            # observation.
            if (
                observation_id
                in used_observation_ids
            ):
                continue


            photos = (
                observation.get(
                    "photos",
                    []
                )
            )


            if not photos:
                continue


            photo = photos[0]

            photo_id = (
                photo.get("id")
            )


            if (
                photo_id
                in used_photo_ids
            ):
                continue


            photo_url = (
                get_photo_url(photo)
            )


            if not photo_url:
                continue


            filename = (
                f"{folder_name}_"
                f"{downloaded + 1:04d}"
                f".jpg"
            )


            destination = (
                species_dir
                / filename
            )


            print(
                f"[{downloaded + 1}/"
                f"{IMAGES_PER_SPECIES}] "
                f"{filename}"
            )


            success = download_image(
                photo_url,
                destination
            )


            if not success:
                continue


            used_photo_ids.add(
                photo_id
            )

            used_observation_ids.add(
                observation_id
            )


            downloaded += 1


            user = (
                observation.get(
                    "user",
                    {}
                )
            )


            geojson = (
                observation.get(
                    "geojson"
                )
                or {}
            )


            coordinates = (
                geojson.get(
                    "coordinates",
                    [None, None]
                )
            )


            metadata.append({

                "filename":
                    str(destination),

                "species_label":
                    folder_name,

                "scientific_name":
                    scientific_name,

                "taxon_id":
                    taxon_id,

                "observation_id":
                    observation_id,

                "photo_id":
                    photo_id,

                "observer":
                    user.get(
                        "login"
                    ),

                "observed_on":
                    observation.get(
                        "observed_on"
                    ),

                "latitude":
                    (
                        coordinates[1]
                        if len(coordinates) > 1
                        else None
                    ),

                "longitude":
                    (
                        coordinates[0]
                        if coordinates
                        else None
                    ),

                "photo_url":
                    photo_url,

                "license":
                    photo.get(
                        "license_code"
                    ),

            })


            # Don't hammer the
            # image server.
            time.sleep(1)


        page += 1

        # Small break between
        # observation pages.
        time.sleep(3)


    print()
    print(
        f"{scientific_name}: "
        f"{downloaded} images "
        f"downloaded."
    )


    # Pause before next taxon.
    time.sleep(5)


# ============================================================
# SAVE METADATA
# ============================================================

df = pd.DataFrame(
    metadata
)


metadata_path = (
    OUTPUT_DIR
    / "metadata.csv"
)


df.to_csv(
    metadata_path,
    index=False
)


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 70)
print("DOWNLOAD COMPLETE")
print("=" * 70)

print(
    f"Total downloaded: "
    f"{len(df)}"
)


if not df.empty:

    print()
    print("Species counts:")

    print(
        df[
            "species_label"
        ]
        .value_counts()
        .to_string()
    )


print()
print(
    f"Metadata saved to:\n"
    f"{metadata_path}"
)