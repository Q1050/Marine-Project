from pathlib import Path
import json

import numpy as np
import open_clip
import torch
from PIL import Image


# ============================================================
# CONFIG
# ============================================================

REFERENCE_DIR = Path("data/split/reference")
OUTPUT_DIR = Path("embeddings")

MODEL_NAME = "hf-hub:imageomics/bioclip-2"

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

print("=" * 60)
print("BIOCLIP REFERENCE EMBEDDING GENERATOR")
print("=" * 60)

print(f"Using device: {device}")


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

print("BioCLIP 2 loaded successfully.")


# ============================================================
# FIND REFERENCE IMAGES
# ============================================================

if not REFERENCE_DIR.exists():
    raise FileNotFoundError(
        f"Reference directory does not exist: "
        f"{REFERENCE_DIR}"
    )


image_paths = [
    path
    for path in REFERENCE_DIR.rglob("*")
    if (
        path.is_file()
        and path.suffix.lower()
        in SUPPORTED_EXTENSIONS
    )
]


if not image_paths:
    raise RuntimeError(
        f"No images found inside "
        f"{REFERENCE_DIR}"
    )


print(
    f"\nFound {len(image_paths)} "
    f"reference images."
)


# ============================================================
# STORAGE
# ============================================================

embeddings = []
metadata = []


# ============================================================
# GENERATE EMBEDDINGS
# ============================================================

print("\nGenerating embeddings...\n")


for index, image_path in enumerate(
    image_paths,
    start=1
):

    # Because the folder name is our label:
    #
    # reference/
    #     pterois_volitans/
    #         image.jpg
    #
    # species_label becomes:
    # pterois_volitans

    species_label = image_path.parent.name

    try:

        image = Image.open(
            image_path
        ).convert("RGB")

        image_tensor = (
            preprocess(image)
            .unsqueeze(0)
            .to(device)
        )


        # We aren't training.
        # No gradients are required.

        with torch.no_grad():

            embedding = (
                model.encode_image(
                    image_tensor
                )
            )


            # Normalize the embedding.
            #
            # This will make cosine similarity
            # easier later.

            embedding = (
                embedding
                / embedding.norm(
                    dim=-1,
                    keepdim=True
                )
            )


        # Move from GPU/CPU tensor
        # into ordinary NumPy data.

        embedding = (
            embedding
            .squeeze(0)
            .cpu()
            .numpy()
            .astype(np.float32)
        )


        embeddings.append(
            embedding
        )


        metadata.append({
            "image_path":
                str(image_path),

            "filename":
                image_path.name,

            "species_label":
                species_label,
        })


        print(
            f"[{index}/{len(image_paths)}] "
            f"{species_label} "
            f"-> {image_path.name}"
        )


    except Exception as exc:

        print(
            f"[ERROR] "
            f"{image_path}: "
            f"{exc}"
        )


# ============================================================
# VALIDATE RESULTS
# ============================================================

if not embeddings:
    raise RuntimeError(
        "No embeddings were generated."
    )


embedding_matrix = np.vstack(
    embeddings
)


# ============================================================
# SAVE
# ============================================================

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


embedding_file = (
    OUTPUT_DIR
    / "reference_embeddings.npy"
)

metadata_file = (
    OUTPUT_DIR
    / "reference_metadata.json"
)


np.save(
    embedding_file,
    embedding_matrix
)


with open(
    metadata_file,
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        metadata,
        file,
        indent=2,
        ensure_ascii=False
    )


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 60)
print("COMPLETE")
print("=" * 60)

print(
    f"Images encoded: "
    f"{len(embeddings)}"
)

print(
    f"Embedding dimensions: "
    f"{embedding_matrix.shape}"
)

print(
    f"\nEmbeddings saved to:\n"
    f"{embedding_file}"
)

print(
    f"\nMetadata saved to:\n"
    f"{metadata_file}"
)


print("\nSpecies breakdown:")

species_counts = {}

for item in metadata:

    species = item[
        "species_label"
    ]

    species_counts[species] = (
        species_counts.get(
            species,
            0
        ) + 1
    )


for species, count in species_counts.items():

    print(
        f"  {species}: {count}"
    )