from pathlib import Path
import json

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

TOP_K = 5

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
print("BIOCLIP SPECIES MATCHING TEST")
print("=" * 70)

print(f"Using device: {device}")


# ============================================================
# LOAD REFERENCE EMBEDDINGS
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
    f"Loaded "
    f"{len(reference_embeddings)} "
    f"reference embeddings."
)

print(
    f"Embedding dimensions: "
    f"{reference_embeddings.shape}"
)


# ============================================================
# LOAD BIOCLIP
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
# IMAGE ENCODING FUNCTION
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
# FIND TEST IMAGES
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
        f"No test images found in "
        f"{TEST_DIR}"
    )

print(
    f"\nFound "
    f"{len(test_images)} "
    f"test images."
)


# ============================================================
# TEST LOOP
# ============================================================

correct = 0
total = 0

results = []


for image_path in test_images:

    expected_species = (
        image_path.parent.name
    )

    test_embedding = encode_image(
        image_path
    )

    # Since both reference and test embeddings
    # are normalized, dot product = cosine similarity.
    similarities = (
        reference_embeddings
        @ test_embedding
    )

    top_indices = np.argsort(
        similarities
    )[::-1][:TOP_K]


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

    print("\nTOP MATCHES:")


    species_scores = {}


    for rank, index in enumerate(
        top_indices,
        start=1
    ):

        metadata = (
            reference_metadata[index]
        )

        species = metadata[
            "species_label"
        ]

        similarity = float(
            similarities[index]
        )

        print(
            f"{rank}. "
            f"{species:<25} "
            f"{similarity:.4f} "
            f"({metadata['filename']})"
        )


        # Keep best score for each species.
        if (
            species not in species_scores
            or similarity
            > species_scores[species]
        ):
            species_scores[
                species
            ] = similarity


    # Prediction is species of
    # highest-scoring reference image.

    best_index = top_indices[0]

    predicted_species = (
        reference_metadata[
            best_index
        ]["species_label"]
    )

    best_similarity = float(
        similarities[
            best_index
        ]
    )


    is_correct = (
        predicted_species
        == expected_species
    )

    if is_correct:
        correct += 1

    total += 1


    print()

    print(
        f"PREDICTED: "
        f"{predicted_species}"
    )

    print(
        f"SIMILARITY: "
        f"{best_similarity:.4f}"
    )

    print(
        f"RESULT: "
        f"{'CORRECT' if is_correct else 'WRONG'}"
    )


    results.append({
        "image": image_path.name,
        "expected": expected_species,
        "predicted": predicted_species,
        "similarity": best_similarity,
        "correct": is_correct,
    })


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


print("\nIndividual results:")

for result in results:

    print(
        f"{result['image']:<35} "
        f"Expected: "
        f"{result['expected']:<25} "
        f"Predicted: "
        f"{result['predicted']:<25} "
        f"Score: "
        f"{result['similarity']:.4f}"
    )