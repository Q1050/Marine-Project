from pathlib import Path
from collections import defaultdict
import json

import numpy as np
import open_clip
import torch
from PIL import Image

from anomaly_engine import evaluate_observation


# ============================================================
# CONFIG
# ============================================================

IMAGE_PATH = Path(
    "test_image.jpg"
)

REFERENCE_EMBEDDINGS_FILE = Path(
    "embeddings/ground_species/reference_embeddings.npy"
)

REFERENCE_METADATA_FILE = Path(
    "embeddings/ground_species/reference_metadata.json"
)

MODEL_NAME = (
    "hf-hub:imageomics/bioclip-2"
)

TOP_IMAGES_PER_SPECIES = 3

TOP_SPECIES_TO_SHOW = 5


# ============================================================
# LABEL → SCIENTIFIC NAME
# ============================================================

SCIENTIFIC_NAMES = {

    "acanthurus_bahianus":
        "Acanthurus bahianus",

    "acanthurus_coeruleus":
        "Acanthurus coeruleus",

    "diodon_hystrix":
        "Diodon hystrix",

    "gymnothorax_funebris":
        "Gymnothorax funebris",

    "holacanthus_ciliaris":
        "Holacanthus ciliaris",

    "lactophrys_triqueter":
        "Lactophrys triqueter",

    "pomacanthus_paru":
        "Pomacanthus paru",

    "pterois_volitans":
        "Pterois volitans",

    "sparisoma_viride":
        "Sparisoma viride",

    "sphyraena_barracuda":
        "Sphyraena barracuda",
}


# ============================================================
# DEVICE
# ============================================================

device = torch.device(
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
)

print("=" * 80)
print("MARINE OBSERVATION PIPELINE")
print("=" * 80)

print(
    f"Device: {device}"
)


# ============================================================
# VALIDATE IMAGE
# ============================================================

if not IMAGE_PATH.exists():

    raise FileNotFoundError(
        f"Image not found: "
        f"{IMAGE_PATH}"
    )


# ============================================================
# LOAD REFERENCE DATABASE
# ============================================================

reference_embeddings = np.load(
    REFERENCE_EMBEDDINGS_FILE
)


with open(
    REFERENCE_METADATA_FILE,
    "r",
    encoding="utf-8"
) as file:

    reference_metadata = json.load(
        file
    )


print(
    f"Reference images: "
    f"{len(reference_embeddings)}"
)


# ============================================================
# LOAD BIOCLIP
# ============================================================

print(
    "\nLoading BioCLIP 2..."
)

model, _, preprocess = (
    open_clip.create_model_and_transforms(
        MODEL_NAME
    )
)

model = model.to(
    device
)

model.eval()

print(
    "BioCLIP loaded."
)


# ============================================================
# ENCODE IMAGE
# ============================================================

def encode_image(
    image_path
):

    image = Image.open(
        image_path
    ).convert(
        "RGB"
    )


    image_tensor = (
        preprocess(image)
        .unsqueeze(0)
        .to(device)
    )


    with torch.no_grad():

        embedding = (
            model.encode_image(
                image_tensor
            )
        )

        embedding = (
            embedding
            /
            embedding.norm(
                dim=-1,
                keepdim=True
            )
        )


    return (
        embedding
        .squeeze(0)
        .cpu()
        .numpy()
        .astype(
            np.float32
        )
    )


# ============================================================
# SPECIES MATCHING
# ============================================================

def identify_species(
    image_path
):

    embedding = encode_image(
        image_path
    )


    similarities = (
        reference_embeddings
        @ embedding
    )


    species_to_scores = (
        defaultdict(list)
    )


    for index, similarity in enumerate(
        similarities
    ):

        label = (
            reference_metadata[
                index
            ][
                "species_label"
            ]
        )

        species_to_scores[
            label
        ].append(
            float(
                similarity
            )
        )


    species_scores = {}


    for label, scores in (
        species_to_scores.items()
    ):

        top_scores = sorted(
            scores,
            reverse=True
        )[
            :TOP_IMAGES_PER_SPECIES
        ]


        species_scores[
            label
        ] = (
            sum(top_scores)
            /
            len(top_scores)
        )


    ranked = sorted(
        species_scores.items(),
        key=lambda item:
            item[1],
        reverse=True
    )


    top_label = (
        ranked[0][0]
    )

    top_score = (
        ranked[0][1]
    )


    second_label = (
        ranked[1][0]
    )

    second_score = (
        ranked[1][1]
    )


    margin = (
        top_score
        - second_score
    )


    return {

        "top_label":
            top_label,

        "top_score":
            top_score,

        "second_label":
            second_label,

        "second_score":
            second_score,

        "margin":
            margin,

        "ranked":
            ranked,
    }


# ============================================================
# RUN VISION
# ============================================================

vision = identify_species(
    IMAGE_PATH
)


predicted_label = (
    vision[
        "top_label"
    ]
)


predicted_species = (
    SCIENTIFIC_NAMES.get(
        predicted_label
    )
)


if predicted_species is None:

    raise RuntimeError(
        f"No scientific-name mapping "
        f"for: {predicted_label}"
    )


# ============================================================
# VISION OUTPUT
# ============================================================

print()
print("=" * 80)
print("VISION RESULT")
print("=" * 80)

print(
    f"Image: "
    f"{IMAGE_PATH}"
)


print(
    f"\nTop prediction: "
    f"{predicted_species}"
)

print(
    f"Top score: "
    f"{vision['top_score']:.4f}"
)

print(
    f"Second score: "
    f"{vision['second_score']:.4f}"
)

print(
    f"Margin: "
    f"{vision['margin']:.4f}"
)


print()
print(
    f"TOP "
    f"{TOP_SPECIES_TO_SHOW} "
    f"CANDIDATES"
)

print(
    "-" * 60
)


for rank, (
    label,
    score
) in enumerate(
    vision[
        "ranked"
    ][
        :TOP_SPECIES_TO_SHOW
    ],
    start=1
):

    scientific_name = (
        SCIENTIFIC_NAMES.get(
            label,
            label
        )
    )

    print(
        f"{rank}. "
        f"{scientific_name:<28} "
        f"{score:.4f}"
    )


# ============================================================
# ANOMALY ENGINE
# ============================================================

result = evaluate_observation(

    species_name=
        predicted_species,

    vision_score=
        vision[
            "top_score"
        ],

    vision_margin=
        vision[
            "margin"
        ],
)


# ============================================================
# FINAL ASSESSMENT
# ============================================================

print()
print("=" * 80)
print("FINAL OBSERVATION ASSESSMENT")
print("=" * 80)


print(
    f"Species candidate: "
    f"{result.species}"
)


print(
    f"Vision accepted: "
    f"{result.vision_accepted}"
)


print(
    f"Regional evidence:"
)

print(
    f"  Species: "
    f"{result.species_records}"
)

print(
    f"  Genus:   "
    f"{result.genus_records}"
)

print(
    f"  Family:  "
    f"{result.family_records}"
)


print(
    f"\nEcological status: "
    f"{result.ecological_status}"
)


print(
    f"Decision: "
    f"{result.decision}"
)


print(
    f"Priority: "
    f"{result.priority}"
)


print(
    f"\nReason:\n"
    f"{result.reason}"
)