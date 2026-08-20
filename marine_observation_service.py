from pathlib import Path
from collections import defaultdict
import json
import hashlib
import numpy as np
import open_clip
import torch
from PIL import Image

from regional_evidence_provider import RegionalEvidenceProvider


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
# LEGACY COMPAT: JAMAICA ECOLOGICAL STATUS
# ============================================================
#
# This dict is preserved ONLY as a test-compatibility reference and a
# non-authoritative historical record. It MUST NOT be used in production
# observation classification. New ecological classification flows through
# the SpeciesJurisdictionStatus registry. See species_jurisdiction_ecology.
# ============================================================

JAMAICA_ECOLOGICAL_STATUS_LEGACY_COMPAT = {

    "Pterois volitans": "INVASIVE",

    "Sparisoma viride": "NATIVE",

    "Acanthurus coeruleus": "NATIVE",

    "Acanthurus bahianus": "NATIVE",

    "Holacanthus ciliaris": "NATIVE",

    "Pomacanthus paru": "NATIVE",

    "Diodon hystrix": "NATIVE",

    "Gymnothorax funebris": "NATIVE",

    "Sphyraena barracuda": "NATIVE",
}


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
# SERVICE
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

        self.regional_provider = (
            RegionalEvidenceProvider(
                radius_km=100
            )
        )


    # ========================================================
    # REFERENCES
    # ========================================================

    def _load_reference_database(self):

        self.reference_embeddings = np.load(
            REFERENCE_EMBEDDINGS_FILE
        ).astype(np.float32)

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
                "Reference embedding/metadata "
                "length mismatch."
            )

        print(
            f"Loaded "
            f"{len(self.reference_embeddings)} "
            f"reference embeddings."
        )


    # ========================================================
    # BIOCLIP
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
    # ENCODE
    # ========================================================

    def _encode_image(self,image_path):

     resolved_path = Path(
          image_path
     ).resolve()

     print()
     print("IMAGE BEING ENCODED")
     print("-" * 50)

     print(
          "Path:",
          resolved_path
     )

     print(
          "Exists:",
          resolved_path.exists()
     )

     with open(
          resolved_path,
          "rb"
     ) as file:

          file_hash = hashlib.sha256(
               file.read()
          ).hexdigest()

     print(
          "SHA256:",
          file_hash
     )

     image = Image.open(
          resolved_path
     ).convert("RGB")

     print(
          "Image size:",
          image.size
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

            "top_label":
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
    # DECISION LOGIC
    # ========================================================

    @staticmethod
    def determine_pattern(
        species_records,
        genus_records,
        family_records,
    ):

        if species_records > 0:
            return "SPECIES_PRESENT"

        if genus_records > 0:
            return "GENUS_PRESENT"

        if family_records > 0:
            return "FAMILY_PRESENT"

        return "NO_TAXONOMIC_EVIDENCE"


    def make_decision(
        self,
        species_name,
        evidence,
        ecological_status,
    ):
        """Produce the observation decision and priority.

        ``ecological_status`` MUST be resolved upstream through
        ``species_jurisdiction_ecology.resolve_ecological_status`` for the
        observation's jurisdiction. The decision engine MUST NOT
        independently consult a global ecological dictionary.
        """

        species_records = (
            evidence["species"]
            ["records_100km"]
        )

        genus_records = (
            evidence["genus"]
            ["records_100km"]
        )

        family_records = (
            evidence["family"]
            ["records_100km"]
        )

        pattern = self.determine_pattern(
            species_records,
            genus_records,
            family_records,
        )


        if pattern == "SPECIES_PRESENT":

            if (
                ecological_status
                == "INVASIVE"
            ):

                return {
                    "decision":
                        "KNOWN_INVASIVE_RECORD",

                    "priority":
                        "MONITOR",

                    "ecological_status":
                        ecological_status,

                    "reason":
                        (
                            "Exact species has "
                            "regional occurrence "
                            "evidence and is marked "
                            "invasive for the "
                            "prototype region."
                        ),
                }


            return {
                "decision":
                    "NORMAL_REGIONAL_RECORD",

                "priority":
                    "LOW",

                "ecological_status":
                    ecological_status,

                "reason":
                    (
                        "Exact species has "
                        "historical regional "
                        "occurrence evidence."
                    ),
            }


        if pattern == "GENUS_PRESENT":

            return {
                "decision":
                    "SPECIES_LEVEL_ANOMALY",

                "priority":
                    "REVIEW",

                "ecological_status":
                    ecological_status,

                "reason":
                    (
                        "No exact-species regional "
                        "evidence was found, but "
                        "the genus occurs locally."
                    ),
            }


        if pattern == "FAMILY_PRESENT":

            return {
                "decision":
                    "TAXONOMIC_ANOMALY",

                "priority":
                    "HIGH",

                "ecological_status":
                    ecological_status,

                "reason":
                    (
                        "Neither the species nor "
                        "genus has regional evidence, "
                        "but members of the family "
                        "occur locally."
                    ),
            }


        return {
            "decision":
                "HIGH_PRIORITY_REVIEW",

            "priority":
                "HIGH",

            "ecological_status":
                ecological_status,

            "reason":
                (
                    "No regional evidence was "
                    "found for the species, "
                    "genus, or family."
                ),
        }


    # ========================================================
    # COMPLETE ANALYSIS
    # ========================================================

    def analyze(
        self,
        image_path,
        latitude,
        longitude,
        jurisdiction_id,
        db=None,
    ):
        """Analyze an observation and return ecological + decision results.

        ``jurisdiction_id`` is REQUIRED: ecological classification is
        jurisdiction-isolated and MUST be resolved through the
        SpeciesJurisdictionStatus registry. ``db`` is required for the
        registry lookup; if absent, the analysis result reports
        ``ecological_status = "UNKNOWN"`` and the decision engine does
        NOT emit ``KNOWN_INVASIVE_RECORD``.
        """

        identification = self.identify(
            image_path
        )


        # ----------------------------------------------------
        # OPEN-SET REJECTION
        # ----------------------------------------------------

        if not identification[
            "accepted"
        ]:

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
                        "unresolved",

                    "species":
                        None,

                    "nearest_candidate":
                        identification[
                            "scientific_name"
                        ],

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

                "regional_evidence":
                    None,

                "ecological_status":
                    "UNKNOWN",

                "decision":
                    "UNRESOLVED_IDENTIFICATION",

                "priority":
                    "REVIEW",

                "reason":
                    (
                        "Vision identification "
                        "did not meet the open-set "
                        "acceptance threshold."
                    ),
            }


        # ----------------------------------------------------
        # ACCEPTED SPECIES
        # ----------------------------------------------------

        species_name = (
            identification[
                "scientific_name"
            ]
        )


        # ----------------------------------------------------
        # DYNAMIC REGIONAL EVIDENCE
        # ----------------------------------------------------

        evidence = (
            self.regional_provider
            .get_evidence(
                species_name=
                    species_name,

                latitude=
                    latitude,

                longitude=
                    longitude,
            )
        )


        # ----------------------------------------------------
        # ECOLOGICAL STATUS (jurisdiction-isolated)
        # ----------------------------------------------------

        from species_jurisdiction_ecology import (
            resolve_ecological_status as _resolve_registry_status,
        )

        if db is None:
            ecological_status = "UNKNOWN"
        else:
            ecological_status = _resolve_registry_status(
                db, species_name, jurisdiction_id,
            )

        # ----------------------------------------------------
        # DECISION
        # ----------------------------------------------------

        decision = self.make_decision(
            species_name,
            evidence,
            ecological_status,
        )


        return {

            "observation": {
                "image":
                    str(image_path),

                "latitude":
                    float(latitude),

                "longitude":
                    float(longitude),
            },

            "identification": {

                "status":
                    "accepted",

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

            "regional_evidence":
                evidence,

            "ecological_status":
                decision[
                    "ecological_status"
                ],

            "decision":
                decision[
                    "decision"
                ],

            "priority":
                decision[
                    "priority"
                ],

            "reason":
                decision[
                    "reason"
                ],
        }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    service = (
        MarineObservationService()
    )


    result = service.analyze(

        image_path=
            "test_image.jpg",

        latitude=
            18.43,

        longitude=
            -77.10,
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