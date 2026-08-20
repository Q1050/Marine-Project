from pathlib import Path
import json

import numpy as np
import open_clip
import torch
from PIL import Image


# ============================================================
# CONFIG
# ============================================================

REFERENCE_DIR = Path(
    "data/ground_species_dataset/split/reference"
)

OUTPUT_DIR = Path(
    "embeddings/ground_species"
)

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
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
)

print("=" * 70)
print("GROUND SPECIES REFERENCE EMBEDDINGS")
print("=" * 70)

print(f"Device: {device}")


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
# FIND IMAGES
# ============================================================

image_paths = sorted([
    path
    for path in REFERENCE_DIR.rglob("*")
    if (
        path.is_file()
        and path.suffix.lower()
        in SUPPORTED_EXTENSIONS
    )
])

if not image_paths:
    raise RuntimeError(
        f"No reference images found in "
        f"{REFERENCE_DIR}"
    )

print(
    f"\nReference images found: "
    f"{len(image_paths)}"
)


# ============================================================
# ENCODE
# ============================================================

embeddings = []
metadata = []


for index, image_path in enumerate(
    image_paths,
    start=1
):

    species_label = (
        image_path.parent.name
    )

    try:

        image = Image.open(
            image_path
        ).convert("RGB")

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
                / embedding.norm(
                    dim=-1,
                    keepdim=True
                )
            )

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
            f"{species_label}"
        )

    except Exception as exc:

        print(
            f"[ERROR] "
            f"{image_path}: "
            f"{exc}"
        )


# ============================================================
# SAVE
# ============================================================

if not embeddings:
    raise RuntimeError(
        "No embeddings generated."
    )

embedding_matrix = np.vstack(
    embeddings
)

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
print("=" * 70)
print("COMPLETE")
print("=" * 70)

print(
    f"Images encoded: "
    f"{len(embeddings)}"
)

print(
    f"Embedding shape: "
    f"{embedding_matrix.shape}"
)

print(
    f"\nSaved embeddings to:\n"
    f"{embedding_file}"
)

print(
    f"\nSaved metadata to:\n"
    f"{metadata_file}"
)