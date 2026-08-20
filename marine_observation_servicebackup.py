from pathlib import Path
from collections import defaultdict
from dataclasses import asdict
import json

import numpy as np
import open_clip
import pandas as pd
import torch
from PIL import Image

from anomaly_engine import evaluate_observation


# ============================================================
# CONFIG
# ============================================================

MODEL_NAME = "hf-hub:imageomics/bioclip-2"

REFERENCE_EMBEDDINGS_FILE = Path(
    "embeddings/ground_species/reference_embeddings.npy"
)

REFERENCE_METADATA_FILE = Path(
    "embeddings/ground_species/reference_metadata.json"
)

TOP_IMAGES_PER_SPECIES = 3
TOP_CANDIDATES = 5

VISION_SCORE_THRESHOLD = 0.805
VISION_MARGIN_THRESHOLD = 0.040


# ============================================================
# SCIENTIFIC NAMES
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
# MARINE OBSERVATION SERVICE
# ============================================================

class MarineObservationService:

    def __init__(self):

        self.device = torch.device(
            "cuda"
            if torch.cuda.is_available()
            else "cpu"
        )

        print(
            f"Marine observation service "
            f"starting on: {self.device}"
        )

        self._load_reference_database()
        self._load_model()


    # ========================================================
    # LOAD REFERENCES
    # ========================================================

    def _load_reference_database(self):

        self.reference_embeddings = np.load(
            REFERENCE_EMBEDDINGS_FILE
        ).astype(
            np.float32
        )

        with open(
            REFERENCE_METADATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            self.reference_metadata = (
                json.load(file)
            )

        if (
            len(self.reference_embeddings)
            !=
            len(self.reference_metadata)
        ):

            raise RuntimeError(
                "Reference embeddings and "
                "metadata have different lengths."
            )

        print(
            f"Loaded "
            f"{len(self.reference_embeddings)} "
            f"reference embeddings."
        )


    # ========================================================
    # LOAD BIOCLIP
    # ========================================================

    def _load_model(self):

        print("Loading BioCLIP 2...")

        self.model, _, self.preprocess = (
            open_clip
            .create_model_and_transforms(
                MODEL_NAME
            )
        )

        self.model = self.model.to(
            self.device
        )

        self.model.eval()

        print("BioCLIP loaded.")


    # ========================================================
    # IMAGE ENCODING
    # ========================================================

    def _encode_image(
        self,
        image_path
    ):

        image = Image.open(
            image_path
        ).convert(
            "RGB"
        )

        image_tensor = (
            self.preprocess(image)
            .unsqueeze(0)
            .to(self.device)
        )

        with torch.no_grad():

            embedding = (
                self.model.encode_image(
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
            .astype(np.float32)
        )


    # ========================================================
    # IDENTIFICATION
    # ========================================================

    def identify(
        self,
        image_path
    ):

        image_path = Path(
            image_path
        )

        if not image_path.exists():

            raise FileNotFoundError(
                f"Image not found: "
                f"{image_path}"
            )

        embedding = self._encode_image(
            image_path
        )

        similarities = (
            self.reference_embeddings
            @ embedding
        )

        grouped_scores = (
            defaultdict(list)
        )

        for index, similarity in enumerate(
            similarities
        ):

            label = (
                self.reference_metadata[
                    index
                ][
                    "species_label"
                ]
            )

            grouped_scores[
                label
            ].append(
                float(similarity)
            )

        species_scores = {}

        for label, scores in (
            grouped_scores.items()
        ):

            top_scores = sorted(
                scores,
                reverse=True
            )[
                :TOP_IMAGES_PER_SPECIES
            ]

            species_scores[label] = (
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

        if len(ranked) < 2:

            raise RuntimeError(
                "At least two reference "
                "species are required."
            )

        top_label, top_score = (
            ranked[0]
        )

        second_label, second_score = (
            ranked[1]
        )

        margin = (
            top_score
            - second_score
        )

        accepted = (
            top_score
            >= VISION_SCORE_THRESHOLD
            and
            margin
            >= VISION_MARGIN_THRESHOLD
        )

        candidates = []

        for label, score in (
            ranked[:TOP_CANDIDATES]
        ):

            candidates.append({
                "label":
                    label,

                "scientific_name":
                    SCIENTIFIC_NAMES.get(
                        label,
                        label
                    ),

                "score":
                    round(
                        float(score),
                        6
                    ),
            })

        return {
            "accepted":
                accepted,

            "label":
                top_label,

            "scientific_name":
                SCIENTIFIC_NAMES.get(
                    top_label,
                    top_label
                ),

            "score":
                float(top_score),

            "second_score":
                float(second_score),

            "margin":
                float(margin),

            "candidates":
                candidates,
        }


    # ========================================================
    # COMPLETE OBSERVATION
    # ========================================================

    def analyze(
        self,
        image_path,
        latitude=None,
        longitude=None,
    ):

        identification = self.identify(
            image_path
        )

        species_name = (
            identification[
                "scientific_name"
            ]
        )

        anomaly = evaluate_observation(

            species_name=
                species_name,

            vision_score=
                identification[
                    "score"
                ],

            vision_margin=
                identification[
                    "margin"
                ],
        )

        return {

            "observation": {
                "image":
                    str(image_path),

                "latitude":
                    latitude,

                "longitude":
                    longitude,
            },

            "identification": {
                "status":
                    (
                        "accepted"
                        if identification[
                            "accepted"
                        ]
                        else
                        "unresolved"
                    ),

                "species":
                    species_name,

                "score":
                    round(
                        identification[
                            "score"
                        ],
                        6
                    ),

                "margin":
                    round(
                        identification[
                            "margin"
                        ],
                        6
                    ),

                "candidates":
                    identification[
                        "candidates"
                    ],
            },

            "regional_evidence": {

                "species_records":
                    anomaly.species_records,

                "genus_records":
                    anomaly.genus_records,

                "family_records":
                    anomaly.family_records,
            },

            "ecological_status":
                anomaly.ecological_status,

            "decision":
                anomaly.decision,

            "priority":
                anomaly.priority,

            "reason":
                anomaly.reason,
        }


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":

    service = (
        MarineObservationService()
    )

    result = service.analyze(
        image_path="test_image.jpg",
        latitude=18.43,
        longitude=-77.10,
    )

    print()
    print("=" * 80)
    print("MARINE OBSERVATION RESULT")
    print("=" * 80)

    print(
        json.dumps(
            result,
            indent=2
        )
    )