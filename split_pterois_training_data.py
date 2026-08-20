from pathlib import Path
import random
import shutil


SOURCE_DIR = Path("data/pterois_dataset/raw")
OUTPUT_DIR = Path("data/pterois_dataset/split")

TRAIN_RATIO = 0.70
VALIDATION_RATIO = 0.15
TEST_RATIO = 0.15

RANDOM_SEED = 42

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


random.seed(RANDOM_SEED)


species_folders = [
    folder
    for folder in SOURCE_DIR.iterdir()
    if folder.is_dir()
]


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

    random.shuffle(images)

    total = len(images)

    train_count = int(total * TRAIN_RATIO)
    validation_count = int(total * VALIDATION_RATIO)

    train_images = images[:train_count]

    validation_images = images[
        train_count:
        train_count + validation_count
    ]

    test_images = images[
        train_count + validation_count:
    ]


    splits = {
        "train": train_images,
        "validation": validation_images,
        "test": test_images,
    }


    for split_name, split_images in splits.items():

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


    print(species_dir.name)

    print(
        f"  Train:      "
        f"{len(train_images)}"
    )

    print(
        f"  Validation: "
        f"{len(validation_images)}"
    )

    print(
        f"  Test:       "
        f"{len(test_images)}"
    )


print()
print("Dataset split complete.")