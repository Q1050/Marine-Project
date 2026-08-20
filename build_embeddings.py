from pathlib import Path
import time

import pandas as pd
import requests


SPECIES = {
    "pterois_volitans": "Pterois volitans",
    "pterois_miles": "Pterois miles",
    "scorpaena_plumieri": "Scorpaena plumieri",
    "sparisoma_viride": "Sparisoma viride",
}

IMAGES_PER_SPECIES = 10

OUTPUT_DIR = Path("data/reference")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()

session.headers.update({
    "User-Agent": "MarineIntelligenceBuildathon/0.1"
})


def find_taxon(scientific_name):
    url = "https://api.inaturalist.org/v1/taxa"

    params = {
        "q": scientific_name,
        "rank": "species",
        "per_page": 10,
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


def get_observations(taxon_id, limit=10):

    url = (
        "https://api.inaturalist.org/"
        "v1/observations"
    )

    params = {
        "taxon_id": taxon_id,

        # Research-grade only.
        "quality_grade": "research",

        # Must contain a photo.
        "photos": "true",

        # Ask for extra observations because
        # some might have unsuitable licences.
        "per_page": min(limit * 4, 100),

        # Prefer recent observations.
        "order_by": "created_at",
        "order": "desc",
    }

    response = session.get(
        url,
        params=params,
        timeout=60,
    )

    response.raise_for_status()

    return response.json().get(
        "results",
        []
    )


def get_photo_url(photo):

    url = photo.get("url")

    if not url:
        return None

    # iNaturalist typically returns URLs
    # containing "square".
    #
    # Replace that with a useful image size.
    return url.replace(
        "/square.",
        "/large."
    )


def download_image(url, destination):

    try:
        response = session.get(
            url,
            timeout=60,
        )

        if response.status_code == 429:
            print(
                "Rate limited. "
                "Waiting 30 seconds..."
            )

            time.sleep(30)

            return False

        response.raise_for_status()

        destination.write_bytes(
            response.content
        )

        return True

    except requests.RequestException as exc:
        print(
            f"Download failed: {exc}"
        )

        return False


metadata = []


for folder_name, scientific_name in SPECIES.items():

    print()
    print("=" * 60)
    print(scientific_name)
    print("=" * 60)

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
        f"iNaturalist taxon ID: "
        f"{taxon_id}"
    )

    species_dir = (
        OUTPUT_DIR / folder_name
    )

    species_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    observations = get_observations(
        taxon_id,
        IMAGES_PER_SPECIES,
    )

    print(
        f"Found {len(observations)} "
        f"candidate observations."
    )

    downloaded = 0

    used_photo_ids = set()

    for observation in observations:

        if downloaded >= IMAGES_PER_SPECIES:
            break

        photos = observation.get(
            "photos",
            []
        )

        if not photos:
            continue

        # Use one image per observation so that
        # we don't accidentally fill the dataset
        # with several nearly-identical shots
        # of one animal.
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
            f"{downloaded + 1:03d}.jpg"
        )

        destination = (
            species_dir / filename
        )

        print(
            f"Trying {filename}"
        )

        success = download_image(
            photo_url,
            destination,
        )

        if not success:
            continue

        used_photo_ids.add(
            photo_id
        )

        downloaded += 1

        user = observation.get(
            "user",
            {}
        )

        taxon_data = observation.get(
            "taxon",
            {}
        )

        metadata.append({
            "filename": str(destination),

            "species_label": folder_name,

            "scientific_name":
                scientific_name,

            "taxon_id":
                taxon_id,

            "observation_id":
                observation.get("id"),

            "photo_id":
                photo_id,

            "observer":
                user.get("login"),

            "observed_on":
                observation.get(
                    "observed_on"
                ),

            "latitude":
                observation.get(
                    "geojson",
                    {}
                ).get(
                    "coordinates",
                    [None, None]
                )[1],

            "longitude":
                observation.get(
                    "geojson",
                    {}
                ).get(
                    "coordinates",
                    [None, None]
                )[0],

            "photo_url":
                photo_url,

            "license":
                photo.get(
                    "license_code"
                ),

            "taxon_name":
                taxon_data.get(
                    "name"
                ),
        })

        print(
            f"Downloaded "
            f"{downloaded}/"
            f"{IMAGES_PER_SPECIES}"
        )

        # Be conservative.
        time.sleep(3)

    print(
        f"Finished: "
        f"{downloaded} images."
    )

    time.sleep(5)


df = pd.DataFrame(metadata)

metadata_path = (
    OUTPUT_DIR / "metadata.csv"
)

df.to_csv(
    metadata_path,
    index=False,
)

print()
print("=" * 60)
print("COMPLETE")
print("=" * 60)

print(
    f"Downloaded "
    f"{len(df)} images."
)

print(
    f"Metadata: "
    f"{metadata_path}"
)