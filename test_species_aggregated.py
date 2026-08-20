from pathlib import Path
import json
from collections import defaultdict

import numpy as np
import open_clip
import torch
from PIL import Image


# ============================================================
# CONFIG
# ============================================================

TEST_DIR = Path("data/split/test")

REFERENCE_EMBEDDINGS_FILE = Path(
    "embeddings/reference_embeddings.npy"
)

REFERENCE_METADATA_FILE = Path(
    "embeddings/reference_metadata.json"
)

MODEL_NAME = "hf-hub:imageomics/bioclip-2"

TOP_IMAGES_PER_SPECIES = 3

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


# ============================================================
# DEVICE
# ============================================================

device = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)

print("=" * 70)
print("BIOCLIP AGGREGATED SPECIES TEST")
print("=" * 70)

print(f"Using device: {device}")


# ============================================================
# LOAD REFERENCE DATA
# ============================================================

reference_embeddings = np.load(
    REFERENCE_EMBEDDINGS_FILE
)

with open(
    REFERENCE_METADATA_FILE,
    "r",
    encoding="utf-8"
) as file:
    reference_metadata = json.load(file)


print(
    f"Loaded {len(reference_embeddings)} "
    f"reference embeddings."
)


# ============================================================
# LOAD MODEL
# ============================================================

print("\nLoading BioCLIP 2...")

model, _, preprocess = (
    open_clip.create_model_and_transforms(
        MODEL_NAME
    )
)

model = model.to(device)
model.eval()

print("BioCLIP 2 loaded.")


# ============================================================
# IMAGE ENCODER
# ============================================================

def encode_image(image_path):
    image = Image.open(
        image_path
    ).convert("RGB")

    image_tensor = (
        preprocess(image)
        .unsqueeze(0)
        .to(device)
    )

    with torch.no_grad():
        embedding = model.encode_image(
            image_tensor
        )

        embedding = (
            embedding
            / embedding.norm(
                dim=-1,
                keepdim=True
            )
        )

    return (
        embedding
        .squeeze(0)
        .cpu()
        .numpy()
        .astype(np.float32)
    )


# ============================================================
# TEST IMAGES
# ============================================================

test_images = [
    path
    for path in TEST_DIR.rglob("*")
    if (
        path.is_file()
        and path.suffix.lower()
        in SUPPORTED_EXTENSIONS
    )
]

if not test_images:
    raise RuntimeError(
        f"No test images found in {TEST_DIR}"
    )


correct = 0
total = 0


for image_path in test_images:

    expected_species = (
        image_path.parent.name
    )

    test_embedding = encode_image(
        image_path
    )

    similarities = (
        reference_embeddings
        @ test_embedding
    )


    # --------------------------------------------------------
    # GROUP SIMILARITIES BY SPECIES
    # --------------------------------------------------------

    species_to_scores = defaultdict(list)

    for index, similarity in enumerate(
        similarities
    ):
        species = reference_metadata[
            index
        ]["species_label"]

        species_to_scores[
            species
        ].append(
            float(similarity)
        )


    # --------------------------------------------------------
    # SCORE EACH SPECIES
    # --------------------------------------------------------

    species_scores = {}

    for species, scores in (
        species_to_scores.items()
    ):

        scores_sorted = sorted(
            scores,
            reverse=True
        )

        top_scores = scores_sorted[
            :TOP_IMAGES_PER_SPECIES
        ]

        average_score = (
            sum(top_scores)
            / len(top_scores)
        )

        species_scores[
            species
        ] = average_score


    ranked_species = sorted(
        species_scores.items(),
        key=lambda item: item[1],
        reverse=True
    )


    predicted_species = (
        ranked_species[0][0]
    )

    predicted_score = (
        ranked_species[0][1]
    )

    second_score = (
        ranked_species[1][1]
        if len(ranked_species) > 1
        else 0
    )

    margin = (
        predicted_score
        - second_score
    )


    is_correct = (
        predicted_species
        == expected_species
    )

    if is_correct:
        correct += 1

    total += 1


    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    print()
    print("=" * 70)

    print(
        f"TEST IMAGE: "
        f"{image_path.name}"
    )

    print(
        f"EXPECTED: "
        f"{expected_species}"
    )

    print("\nSPECIES SCORES:")

    for rank, (
        species,
        score
    ) in enumerate(
        ranked_species,
        start=1
    ):

        print(
            f"{rank}. "
            f"{species:<25} "
            f"{score:.4f}"
        )


    print()

    print(
        f"PREDICTED: "
        f"{predicted_species}"
    )

    print(
        f"SCORE: "
        f"{predicted_score:.4f}"
    )

    print(
        f"MARGIN OVER SECOND: "
        f"{margin:.4f}"
    )

    print(
        f"RESULT: "
        f"{'CORRECT' if is_correct else 'WRONG'}"
    )


# ============================================================
# FINAL SUMMARY
# ============================================================

accuracy = (
    correct / total
    if total
    else 0
)

print()
print("=" * 70)
print("FINAL RESULTS")
print("=" * 70)

print(
    f"Correct: "
    f"{correct}/{total}"
)

print(
    f"Accuracy: "
    f"{accuracy * 100:.2f}%"
)