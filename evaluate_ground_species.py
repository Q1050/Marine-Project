from pathlib import Path
from collections import defaultdict
import json

import numpy as np
import open_clip
import torch
from PIL import Image


# ============================================================
# CONFIG
# ============================================================

TEST_DIR = Path(
    "data/ground_species_dataset/split/test"
)

REFERENCE_EMBEDDINGS_FILE = Path(
    "embeddings/ground_species/reference_embeddings.npy"
)

REFERENCE_METADATA_FILE = Path(
    "embeddings/ground_species/reference_metadata.json"
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
# TAXONOMY FOR THIS CONTROLLED TEST SET
# ============================================================

TAXONOMY = {

    "acanthurus_bahianus": {
        "genus": "Acanthurus",
        "family": "Acanthuridae",
    },

    "acanthurus_coeruleus": {
        "genus": "Acanthurus",
        "family": "Acanthuridae",
    },

    "diodon_hystrix": {
        "genus": "Diodon",
        "family": "Diodontidae",
    },

    "gymnothorax_funebris": {
        "genus": "Gymnothorax",
        "family": "Muraenidae",
    },

    "holacanthus_ciliaris": {
        "genus": "Holacanthus",
        "family": "Pomacanthidae",
    },

    "lactophrys_triqueter": {
        "genus": "Lactophrys",
        "family": "Ostraciidae",
    },

    "pomacanthus_paru": {
        "genus": "Pomacanthus",
        "family": "Pomacanthidae",
    },

    "pterois_volitans": {
        "genus": "Pterois",
        "family": "Scorpaenidae",
    },

    "sparisoma_viride": {
        "genus": "Sparisoma",
        "family": "Scaridae",
    },

    "sphyraena_barracuda": {
        "genus": "Sphyraena",
        "family": "Sphyraenidae",
    },
}


# ============================================================
# DEVICE
# ============================================================

device = torch.device(
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
)

print("=" * 70)
print("GROUND SPECIES EVALUATION")
print("=" * 70)

print(f"Device: {device}")


# ============================================================
# LOAD REFERENCES
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
    f"\nLoaded "
    f"{len(reference_embeddings)} "
    f"reference embeddings."
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
# ENCODE IMAGE
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

test_images = sorted([
    path
    for path in TEST_DIR.rglob("*")
    if (
        path.is_file()
        and path.suffix.lower()
        in SUPPORTED_EXTENSIONS
    )
])


if not test_images:
    raise RuntimeError(
        "No test images found."
    )


print(
    f"Test images found: "
    f"{len(test_images)}"
)


# ============================================================
# TRACKING
# ============================================================

species_correct = 0
genus_correct = 0
family_correct = 0
total = 0


per_species = defaultdict(
    lambda: {
        "correct": 0,
        "total": 0,
    }
)


ambiguous_cases = []


# ============================================================
# EVALUATION LOOP
# ============================================================

for image_path in test_images:

    expected_species = (
        image_path.parent.name
    )

    expected_taxonomy = TAXONOMY[
        expected_species
    ]


    test_embedding = encode_image(
        image_path
    )


    similarities = (
        reference_embeddings
        @ test_embedding
    )


    # --------------------------------------------------------
    # GROUP SCORES BY SPECIES
    # --------------------------------------------------------

    species_to_scores = defaultdict(list)


    for index, similarity in enumerate(
        similarities
    ):

        species = (
            reference_metadata[
                index
            ]["species_label"]
        )

        species_to_scores[
            species
        ].append(
            float(similarity)
        )


    # --------------------------------------------------------
    # AGGREGATE EACH SPECIES
    # --------------------------------------------------------

    species_scores = {}


    for species, scores in (
        species_to_scores.items()
    ):

        top_scores = sorted(
            scores,
            reverse=True
        )[
            :TOP_IMAGES_PER_SPECIES
        ]

        species_scores[
            species
        ] = (
            sum(top_scores)
            / len(top_scores)
        )


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

    second_species = (
        ranked_species[1][0]
    )

    second_score = (
        ranked_species[1][1]
    )

    margin = (
        predicted_score
        - second_score
    )


    predicted_taxonomy = TAXONOMY[
        predicted_species
    ]


    # --------------------------------------------------------
    # LEVEL ACCURACY
    # --------------------------------------------------------

    species_match = (
        predicted_species
        == expected_species
    )

    genus_match = (
        predicted_taxonomy["genus"]
        == expected_taxonomy["genus"]
    )

    family_match = (
        predicted_taxonomy["family"]
        == expected_taxonomy["family"]
    )


    if species_match:
        species_correct += 1

    if genus_match:
        genus_correct += 1

    if family_match:
        family_correct += 1


    total += 1


    per_species[
        expected_species
    ]["total"] += 1


    if species_match:

        per_species[
            expected_species
        ]["correct"] += 1


    # --------------------------------------------------------
    # STORE AMBIGUOUS CASES
    # --------------------------------------------------------

    if margin < 0.03:

        ambiguous_cases.append({

            "image":
                image_path.name,

            "expected":
                expected_species,

            "predicted":
                predicted_species,

            "predicted_score":
                predicted_score,

            "second":
                second_species,

            "second_score":
                second_score,

            "margin":
                margin,

            "correct":
                species_match,

        })


    # --------------------------------------------------------
    # PRINT EACH RESULT
    # --------------------------------------------------------

    print()
    print("=" * 70)

    print(
        f"IMAGE: "
        f"{image_path.name}"
    )

    print(
        f"EXPECTED: "
        f"{expected_species}"
    )

    print("\nTOP 3 SPECIES:")


    for rank, (
        species,
        score
    ) in enumerate(
        ranked_species[:3],
        start=1
    ):

        print(
            f"{rank}. "
            f"{species:<25} "
            f"{score:.4f}"
        )


    print(
        f"\nPREDICTED: "
        f"{predicted_species}"
    )

    print(
        f"MARGIN: "
        f"{margin:.4f}"
    )

    print(
        f"SPECIES: "
        f"{'CORRECT' if species_match else 'WRONG'}"
    )

    print(
        f"GENUS:   "
        f"{'CORRECT' if genus_match else 'WRONG'}"
    )

    print(
        f"FAMILY:  "
        f"{'CORRECT' if family_match else 'WRONG'}"
    )


# ============================================================
# FINAL RESULTS
# ============================================================

species_accuracy = (
    species_correct
    / total
)

genus_accuracy = (
    genus_correct
    / total
)

family_accuracy = (
    family_correct
    / total
)


print()
print("=" * 70)
print("FINAL RESULTS")
print("=" * 70)


print(
    f"Species accuracy: "
    f"{species_correct}/{total} "
    f"({species_accuracy * 100:.2f}%)"
)

print(
    f"Genus accuracy:   "
    f"{genus_correct}/{total} "
    f"({genus_accuracy * 100:.2f}%)"
)

print(
    f"Family accuracy:  "
    f"{family_correct}/{total} "
    f"({family_accuracy * 100:.2f}%)"
)


# ============================================================
# PER-SPECIES RESULTS
# ============================================================

print()
print("=" * 70)
print("PER-SPECIES ACCURACY")
print("=" * 70)


for species in sorted(
    per_species.keys()
):

    correct = (
        per_species[
            species
        ]["correct"]
    )

    count = (
        per_species[
            species
        ]["total"]
    )

    accuracy = (
        correct
        / count
    )


    print(
        f"{species:<25} "
        f"{correct}/{count} "
        f"({accuracy * 100:.2f}%)"
    )


# ============================================================
# AMBIGUOUS CASES
# ============================================================

print()
print("=" * 70)
print("AMBIGUOUS CASES")
print("Margin < 0.03")
print("=" * 70)


print(
    f"Total ambiguous cases: "
    f"{len(ambiguous_cases)}"
)


for case in ambiguous_cases:

    print(
        f"{case['image']:<35} "
        f"{case['predicted']:<23} "
        f"vs "
        f"{case['second']:<23} "
        f"margin={case['margin']:.4f} "
        f"{'CORRECT' if case['correct'] else 'WRONG'}"
    )