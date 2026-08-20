from pathlib import Path
import random
import shutil


# ============================================================
# CONFIG
# ============================================================

SOURCE_DIR = Path(
    "data/ground_species_dataset/raw"
)

OUTPUT_DIR = Path(
    "data/ground_species_dataset/split"
)

REFERENCE_COUNT = 40
TEST_COUNT = 10

RANDOM_SEED = 42

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


# ============================================================
# SETUP
# ============================================================

random.seed(RANDOM_SEED)

species_folders = sorted([
    folder
    for folder in SOURCE_DIR.iterdir()
    if folder.is_dir()
])


# ============================================================
# SPLIT
# ============================================================

for species_dir in species_folders:

    images = [
        file
        for file in species_dir.iterdir()
        if (
            file.is_file()
            and file.suffix.lower()
            in SUPPORTED_EXTENSIONS
        )
    ]

    if len(images) < (
        REFERENCE_COUNT + TEST_COUNT
    ):
        print(
            f"Skipping {species_dir.name}: "
            f"only {len(images)} images."
        )
        continue

    random.shuffle(images)

    reference_images = (
        images[:REFERENCE_COUNT]
    )

    test_images = (
        images[
            REFERENCE_COUNT:
            REFERENCE_COUNT + TEST_COUNT
        ]
    )

    splits = {
        "reference": reference_images,
        "test": test_images,
    }

    for split_name, split_images in (
        splits.items()
    ):

        destination_dir = (
            OUTPUT_DIR
            / split_name
            / species_dir.name
        )

        destination_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        for image in split_images:

            shutil.copy2(
                image,
                destination_dir / image.name
            )

    print(
        f"{species_dir.name:<25} "
        f"Reference: {len(reference_images):2d} | "
        f"Test: {len(test_images):2d}"
    )


print()
print("=" * 60)
print("SPLIT COMPLETE")
print("=" * 60)