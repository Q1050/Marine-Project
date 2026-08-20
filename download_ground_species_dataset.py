from pathlib import Path
import time

import pandas as pd
import requests


# ============================================================
# CONFIG
# ============================================================

SPECIES = {
    "pterois_volitans": "Pterois volitans",
    "sparisoma_viride": "Sparisoma viride",
    "acanthurus_coeruleus": "Acanthurus coeruleus",
    "acanthurus_bahianus": "Acanthurus bahianus",
    "holacanthus_ciliaris": "Holacanthus ciliaris",
    "pomacanthus_paru": "Pomacanthus paru",
    "sphyraena_barracuda": "Sphyraena barracuda",
    "gymnothorax_funebris": "Gymnothorax funebris",
    "lactophrys_triqueter": "Lactophrys triqueter",
    "diodon_hystrix": "Diodon hystrix",
}

IMAGES_PER_SPECIES = 50

OUTPUT_DIR = Path(
    "data/ground_species_dataset/raw"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "MarineIntelligenceBuildathon/0.1"
    )
})


# ============================================================
# FIND EXACT TAXON
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
            taxon.get("name", "").lower()
            == scientific_name.lower()
        ):
            return taxon

    return None


# ============================================================
# OBSERVATIONS
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
        "quality_grade": "research",
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

        return None

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

    return (
        url
        .replace("/square.", "/large.")
        .replace("/small.", "/large.")
        .replace("/medium.", "/large.")
    )


# ============================================================
# DOWNLOAD
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

                wait_time = attempt * 30

                print(
                    f"Image server rate limited. "
                    f"Waiting {wait_time}s..."
                )

                time.sleep(wait_time)

                continue

            response.raise_for_status()

            destination.write_bytes(
                response.content
            )

            return True

        except requests.RequestException as exc:

            print(
                f"Attempt {attempt} failed: "
                f"{exc}"
            )

            time.sleep(attempt * 5)

    return False


# ============================================================
# DOWNLOAD DATASET
# ============================================================

metadata = []


for folder_name, scientific_name in SPECIES.items():

    print()
    print("=" * 70)
    print(scientific_name)
    print("=" * 70)

    taxon = find_taxon(
        scientific_name
    )

    if not taxon:

        print(
            "Exact taxon could not be found."
        )

        continue


    taxon_id = taxon["id"]

    print(
        f"Taxon ID: {taxon_id}"
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

    used_observation_ids = set()
    used_photo_ids = set()


    while downloaded < IMAGES_PER_SPECIES:

        print(
            f"\nFetching page {page}..."
        )

        observations = get_observations(
            taxon_id,
            page
        )


        if observations is None:

            # Rate limited.
            # Retry same page.
            continue


        if not observations:

            print(
                "No additional observations."
            )

            break


        for observation in observations:

            if downloaded >= IMAGES_PER_SPECIES:
                break


            observation_id = (
                observation.get("id")
            )


            if (
                observation_id
                in used_observation_ids
            ):
                continue


            photos = observation.get(
                "photos",
                []
            )


            if not photos:
                continue


            # Only one photo from an observation.
            # Prevents near-duplicate shots
            # of the same animal dominating.
            photo = photos[0]

            photo_id = photo.get("id")


            if photo_id in used_photo_ids:
                continue


            photo_url = get_photo_url(
                photo
            )


            if not photo_url:
                continue


            filename = (
                f"{folder_name}_"
                f"{downloaded + 1:04d}.jpg"
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


            downloaded += 1

            used_observation_ids.add(
                observation_id
            )

            used_photo_ids.add(
                photo_id
            )


            geojson = (
                observation.get("geojson")
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
                        if len(coordinates) > 0
                        else None
                    ),

                "photo_url":
                    photo_url,

                "license":
                    photo.get(
                        "license_code"
                    ),

            })


            time.sleep(1)


        page += 1

        time.sleep(2)


    print()
    print(
        f"{scientific_name}: "
        f"{downloaded} downloaded."
    )

    time.sleep(4)


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
print("GROUND DATASET DOWNLOAD COMPLETE")
print("=" * 70)

print(
    f"Total images: "
    f"{len(df)}"
)


if not df.empty:

    print()
    print(
        df["species_label"]
        .value_counts()
        .sort_index()
        .to_string()
    )


print()
print(
    f"Metadata saved to:\n"
    f"{metadata_path}"
)