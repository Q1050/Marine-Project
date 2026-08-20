from pathlib import Path
import time

import pandas as pd
import requests


# ============================================================
# CONFIG
# ============================================================

SPECIES = {
    "chelonia_mydas": "Chelonia mydas",
    "hippocampus_erectus": "Hippocampus erectus",
    "octopus_briareus": "Octopus briareus",
    "ginglymostoma_cirratum": "Ginglymostoma cirratum",
    "haemulon_flavolineatum": "Haemulon flavolineatum",
}

IMAGES_PER_SPECIES = 10

OUTPUT_DIR = Path(
    "data/unknown_species_testset"
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
    "User-Agent": "MarineIntelligenceBuildathon/0.1"
})


# ============================================================
# FIND TAXON
# ============================================================

def find_taxon(scientific_name):

    response = session.get(
        "https://api.inaturalist.org/v1/taxa",
        params={
            "q": scientific_name,
            "rank": "species",
            "per_page": 20,
        },
        timeout=60,
    )

    response.raise_for_status()

    for taxon in response.json().get(
        "results", []
    ):

        if (
            taxon.get("name", "").lower()
            == scientific_name.lower()
        ):
            return taxon

    return None


# ============================================================
# GET OBSERVATIONS
# ============================================================

def get_observations(
    taxon_id,
    page
):

    response = session.get(
        "https://api.inaturalist.org/v1/observations",
        params={
            "taxon_id": taxon_id,
            "quality_grade": "research",
            "photos": "true",
            "per_page": 100,
            "page": page,
            "order_by": "created_at",
            "order": "desc",
        },
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
        "results", []
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
                timeout=60
            )

            if response.status_code == 429:

                wait = attempt * 30

                print(
                    f"Rate limited. "
                    f"Waiting {wait}s..."
                )

                time.sleep(wait)

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

            time.sleep(
                attempt * 5
            )

    return False


# ============================================================
# DOWNLOAD
# ============================================================

metadata = []


for folder_name, scientific_name in (
    SPECIES.items()
):

    print()
    print("=" * 70)
    print(scientific_name)
    print("=" * 70)

    taxon = find_taxon(
        scientific_name
    )

    if not taxon:

        print("Taxon not found.")
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

    used_observations = set()


    while downloaded < IMAGES_PER_SPECIES:

        observations = get_observations(
            taxon_id,
            page
        )

        if observations is None:
            continue

        if not observations:
            break


        for observation in observations:

            if downloaded >= IMAGES_PER_SPECIES:
                break

            observation_id = (
                observation.get("id")
            )

            if observation_id in used_observations:
                continue

            photos = observation.get(
                "photos", []
            )

            if not photos:
                continue

            photo = photos[0]

            photo_url = get_photo_url(
                photo
            )

            if not photo_url:
                continue

            filename = (
                f"{folder_name}_"
                f"{downloaded + 1:03d}.jpg"
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

            if not download_image(
                photo_url,
                destination
            ):
                continue


            used_observations.add(
                observation_id
            )

            downloaded += 1


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

                "photo_url":
                    photo_url,
            })


            time.sleep(1)


        page += 1
        time.sleep(2)


    print(
        f"\n{scientific_name}: "
        f"{downloaded} downloaded."
    )

    time.sleep(3)


# ============================================================
# SAVE
# ============================================================

df = pd.DataFrame(
    metadata
)

metadata_file = (
    OUTPUT_DIR
    / "metadata.csv"
)

df.to_csv(
    metadata_file,
    index=False
)


print()
print("=" * 70)
print("UNKNOWN DATASET COMPLETE")
print("=" * 70)

print(
    f"Total images: {len(df)}"
)

if not df.empty:

    print()

    print(
        df["species_label"]
        .value_counts()
        .sort_index()
        .to_string()
    )

print(
    f"\nMetadata:\n"
    f"{metadata_file}"
)