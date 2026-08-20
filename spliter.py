from pathlib import Path
import random
import shutil

SOURCE_DIR = Path("data/reference")
REFERENCE_OUT = Path("data/split/reference")
TEST_OUT = Path("data/split/test")

REFERENCE_COUNT = 8
TEST_COUNT = 2

random.seed(42)

species_folders = [
    folder
    for folder in SOURCE_DIR.iterdir()
    if folder.is_dir()
]

for species_dir in species_folders:
    images = [
        file
        for file in species_dir.iterdir()
        if file.suffix.lower() in {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }
    ]

    if len(images) < REFERENCE_COUNT + TEST_COUNT:
        print(
            f"Skipping {species_dir.name}: "
            f"only {len(images)} images found."
        )
        continue

    random.shuffle(images)

    reference_images = images[:REFERENCE_COUNT]
    test_images = images[
        REFERENCE_COUNT:
        REFERENCE_COUNT + TEST_COUNT
    ]

    reference_species_dir = (
        REFERENCE_OUT / species_dir.name
    )
    test_species_dir = (
        TEST_OUT / species_dir.name
    )

    reference_species_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    test_species_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    for image in reference_images:
        shutil.copy2(
            image,
            reference_species_dir / image.name,
        )

    for image in test_images:
        shutil.copy2(
            image,
            test_species_dir / image.name,
        )

    print(
        f"{species_dir.name}: "
        f"{len(reference_images)} reference, "
        f"{len(test_images)} test"
    )

print("Split complete.")