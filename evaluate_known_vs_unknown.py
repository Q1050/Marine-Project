from pathlib import Path
from collections import defaultdict
import json

import numpy as np
import open_clip
import torch
from PIL import Image
import pandas as pd


# ============================================================
# CONFIG
# ============================================================

KNOWN_TEST_DIR = Path(
    "data/ground_species_dataset/split/test"
)

UNKNOWN_TEST_DIR = Path(
    "data/unknown_species_testset"
)

REFERENCE_EMBEDDINGS_FILE = Path(
    "embeddings/ground_species/reference_embeddings.npy"
)

REFERENCE_METADATA_FILE = Path(
    "embeddings/ground_species/reference_metadata.json"
)

MODEL_NAME = "hf-hub:imageomics/bioclip-2"

TOP_IMAGES_PER_SPECIES = 3

OUTPUT_FILE = Path(
    "open_set_scores.csv"
)

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
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
)

print("=" * 70)
print("KNOWN VS UNKNOWN OPEN-SET EVALUATION")
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
    f"\nReference embeddings: "
    f"{len(reference_embeddings)}"
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

print("BioCLIP loaded.")


# ============================================================
# ENCODE
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
# SCORE ONE IMAGE
# ============================================================

def score_image(image_path):

    embedding = encode_image(
        image_path
    )

    similarities = (
        reference_embeddings
        @ embedding
    )

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


    ranked = sorted(
        species_scores.items(),
        key=lambda item: item[1],
        reverse=True
    )

    top_species = ranked[0][0]
    top_score = ranked[0][1]

    second_species = ranked[1][0]
    second_score = ranked[1][1]

    margin = (
        top_score
        - second_score
    )

    return {
        "predicted_species":
            top_species,

        "top_score":
            top_score,

        "second_species":
            second_species,

        "second_score":
            second_score,

        "margin":
            margin,
    }


# ============================================================
# COLLECT FILES
# ============================================================

known_images = sorted([
    path
    for path in KNOWN_TEST_DIR.rglob("*")
    if (
        path.is_file()
        and path.suffix.lower()
        in SUPPORTED_EXTENSIONS
    )
])

unknown_images = sorted([
    path
    for path in UNKNOWN_TEST_DIR.rglob("*")
    if (
        path.is_file()
        and path.suffix.lower()
        in SUPPORTED_EXTENSIONS
    )
])


print(
    f"\nKnown images: "
    f"{len(known_images)}"
)

print(
    f"Unknown images: "
    f"{len(unknown_images)}"
)


# ============================================================
# RUN EVALUATION
# ============================================================

rows = []


print()
print("=" * 70)
print("SCORING KNOWN IMAGES")
print("=" * 70)


for index, image_path in enumerate(
    known_images,
    start=1
):

    result = score_image(
        image_path
    )

    expected_species = (
        image_path.parent.name
    )

    correct = (
        result["predicted_species"]
        == expected_species
    )

    rows.append({
        "group":
            "known",

        "image":
            image_path.name,

        "true_species":
            expected_species,

        "predicted_species":
            result[
                "predicted_species"
            ],

        "top_score":
            result[
                "top_score"
            ],

        "second_species":
            result[
                "second_species"
            ],

        "second_score":
            result[
                "second_score"
            ],

        "margin":
            result[
                "margin"
            ],

        "correct":
            correct,
    })


    print(
        f"[{index}/"
        f"{len(known_images)}] "
        f"{image_path.name:<35} "
        f"score="
        f"{result['top_score']:.4f} "
        f"margin="
        f"{result['margin']:.4f} "
        f"{'OK' if correct else 'WRONG'}"
    )


print()
print("=" * 70)
print("SCORING UNKNOWN IMAGES")
print("=" * 70)


for index, image_path in enumerate(
    unknown_images,
    start=1
):

    result = score_image(
        image_path
    )

    actual_unknown_species = (
        image_path.parent.name
    )

    rows.append({
        "group":
            "unknown",

        "image":
            image_path.name,

        "true_species":
            actual_unknown_species,

        "predicted_species":
            result[
                "predicted_species"
            ],

        "top_score":
            result[
                "top_score"
            ],

        "second_species":
            result[
                "second_species"
            ],

        "second_score":
            result[
                "second_score"
            ],

        "margin":
            result[
                "margin"
            ],

        "correct":
            False,
    })


    print(
        f"[{index}/"
        f"{len(unknown_images)}] "
        f"{image_path.name:<35} "
        f"closest="
        f"{result['predicted_species']:<25} "
        f"score="
        f"{result['top_score']:.4f} "
        f"margin="
        f"{result['margin']:.4f}"
    )


# ============================================================
# DATAFRAME
# ============================================================

df = pd.DataFrame(
    rows
)

df.to_csv(
    OUTPUT_FILE,
    index=False
)


# ============================================================
# SUMMARY
# ============================================================

known_df = df[
    df["group"]
    == "known"
]

unknown_df = df[
    df["group"]
    == "unknown"
]


print()
print("=" * 70)
print("KNOWN SCORE SUMMARY")
print("=" * 70)

print(
    known_df[
        [
            "top_score",
            "margin"
        ]
    ]
    .describe()
    .to_string()
)


print()
print("=" * 70)
print("UNKNOWN SCORE SUMMARY")
print("=" * 70)

print(
    unknown_df[
        [
            "top_score",
            "margin"
        ]
    ]
    .describe()
    .to_string()
)


print()
print("=" * 70)
print("KNOWN CORRECT ONLY")
print("=" * 70)

correct_known_df = (
    known_df[
        known_df["correct"]
        == True
    ]
)

print(
    correct_known_df[
        [
            "top_score",
            "margin"
        ]
    ]
    .describe()
    .to_string()
)


print()
print("=" * 70)
print("SAVED")
print("=" * 70)

print(
    f"Results saved to:\n"
    f"{OUTPUT_FILE}"
)