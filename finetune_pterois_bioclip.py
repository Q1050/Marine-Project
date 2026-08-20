from pathlib import Path
import copy

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.datasets import ImageFolder
import open_clip


# ============================================================
# CONFIG
# ============================================================

TRAIN_DIR = Path(
    "data/pterois_dataset/split/train"
)

VAL_DIR = Path(
    "data/pterois_dataset/split/validation"
)

MODEL_NAME = "hf-hub:imageomics/bioclip-2"

BATCH_SIZE = 8
EPOCHS = 20

CLASSIFIER_LR = 1e-3
BIOCLIP_LR = 1e-5

WEIGHT_DECAY = 1e-4

OUTPUT_DIR = Path("models")

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

MODEL_OUTPUT = (
    OUTPUT_DIR
    / "pterois_bioclip_finetuned.pt"
)


# ============================================================
# DEVICE
# ============================================================

device = torch.device(
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
)

print("=" * 70)
print("PTEROIS BIOCLIP FINE-TUNING")
print("=" * 70)

print(f"Device: {device}")


# ============================================================
# LOAD BIOCLIP
# ============================================================

print("\nLoading BioCLIP 2...")

bioclip, _, preprocess = (
    open_clip.create_model_and_transforms(
        MODEL_NAME
    )
)

bioclip = bioclip.to(device)

print("BioCLIP loaded.")


# ============================================================
# INSPECT VISION MODEL
# ============================================================

print("\nVision backbone type:")

print(
    type(
        bioclip.visual
    )
)


# ============================================================
# FREEZE EVERYTHING FIRST
# ============================================================

for parameter in bioclip.parameters():

    parameter.requires_grad = False


# ============================================================
# UNFREEZE LAST VISION BLOCKS
# ============================================================

unfrozen_parameter_count = 0


if hasattr(
    bioclip.visual,
    "trunk"
):

    trunk = bioclip.visual.trunk

    if hasattr(
        trunk,
        "blocks"
    ):

        blocks = trunk.blocks

        print(
            f"\nVision blocks found: "
            f"{len(blocks)}"
        )

        # Unfreeze last 2 blocks.
        for block in blocks[-2:]:

            for parameter in (
                block.parameters()
            ):

                parameter.requires_grad = True

                unfrozen_parameter_count += (
                    parameter.numel()
                )


elif hasattr(
    bioclip.visual,
    "blocks"
):

    blocks = bioclip.visual.blocks

    print(
        f"\nVision blocks found: "
        f"{len(blocks)}"
    )

    for block in blocks[-2:]:

        for parameter in (
            block.parameters()
        ):

            parameter.requires_grad = True

            unfrozen_parameter_count += (
                parameter.numel()
            )


else:

    print(
        "\nWARNING:"
    )

    print(
        "Could not automatically find "
        "vision transformer blocks."
    )

    print(
        "BioCLIP encoder will remain frozen."
    )


print(
    f"\nUnfrozen BioCLIP parameters: "
    f"{unfrozen_parameter_count:,}"
)


# ============================================================
# IMAGE TRANSFORMS
# ============================================================

# We reuse BioCLIP's final normalization,
# but add training augmentations before it.

# Try to pull mean/std from BioCLIP preprocessing.
normalization = None

for transform in preprocess.transforms:

    if isinstance(
        transform,
        transforms.Normalize
    ):

        normalization = transform


if normalization is None:

    raise RuntimeError(
        "Could not find normalization "
        "inside BioCLIP preprocessing."
    )


train_transform = transforms.Compose([

    transforms.RandomResizedCrop(
        224,
        scale=(
            0.75,
            1.0
        )
    ),

    transforms.RandomHorizontalFlip(
        p=0.5
    ),

    transforms.RandomRotation(
        degrees=10
    ),

    transforms.ColorJitter(
        brightness=0.15,
        contrast=0.15,
        saturation=0.15,
        hue=0.05
    ),

    transforms.ToTensor(),

    normalization,
])


val_transform = preprocess


# ============================================================
# DATASETS
# ============================================================

train_dataset = ImageFolder(
    TRAIN_DIR,
    transform=train_transform
)

val_dataset = ImageFolder(
    VAL_DIR,
    transform=val_transform
)


print("\nClasses:")

for class_name, index in (
    train_dataset.class_to_idx.items()
):

    print(
        f"  {index}: "
        f"{class_name}"
    )


print(
    f"\nTraining images: "
    f"{len(train_dataset)}"
)

print(
    f"Validation images: "
    f"{len(val_dataset)}"
)


# ============================================================
# DATA LOADERS
# ============================================================

train_loader = DataLoader(
    train_dataset,
    batch_size=BATCH_SIZE,
    shuffle=True,
    num_workers=0
)

val_loader = DataLoader(
    val_dataset,
    batch_size=BATCH_SIZE,
    shuffle=False,
    num_workers=0
)


# ============================================================
# FIND EMBEDDING SIZE
# ============================================================

sample_images, _ = next(
    iter(train_loader)
)

sample_images = sample_images.to(
    device
)


bioclip.eval()

with torch.no_grad():

    sample_embeddings = (
        bioclip.encode_image(
            sample_images
        )
    )


embedding_dimension = (
    sample_embeddings.shape[1]
)


print(
    f"\nEmbedding dimension: "
    f"{embedding_dimension}"
)


# ============================================================
# CLASSIFICATION HEAD
# ============================================================

classifier = nn.Sequential(

    nn.Linear(
        embedding_dimension,
        256
    ),

    nn.ReLU(),

    nn.Dropout(
        0.35
    ),

    nn.Linear(
        256,
        len(
            train_dataset.classes
        )
    )

).to(device)


# ============================================================
# OPTIMIZER
# ============================================================

bioclip_trainable_parameters = [

    parameter
    for parameter in bioclip.parameters()
    if parameter.requires_grad

]


parameter_groups = [

    {
        "params":
            classifier.parameters(),

        "lr":
            CLASSIFIER_LR,
    }

]


if bioclip_trainable_parameters:

    parameter_groups.append({

        "params":
            bioclip_trainable_parameters,

        "lr":
            BIOCLIP_LR,

    })


optimizer = torch.optim.AdamW(
    parameter_groups,
    weight_decay=WEIGHT_DECAY
)


criterion = (
    nn.CrossEntropyLoss()
)


scheduler = (
    torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="max",
        factor=0.5,
        patience=3
    )
)


# ============================================================
# TRAINING
# ============================================================

best_validation_accuracy = 0.0

best_checkpoint = None


for epoch in range(
    1,
    EPOCHS + 1
):

    # --------------------------------------------------------
    # TRAIN
    # --------------------------------------------------------

    bioclip.train()
    classifier.train()

    train_loss = 0.0
    train_correct = 0
    train_total = 0


    for images, labels in train_loader:

        images = images.to(
            device
        )

        labels = labels.to(
            device
        )


        optimizer.zero_grad()


        embeddings = (
            bioclip.encode_image(
                images
            )
        )


        embeddings = (
            embeddings
            / embeddings.norm(
                dim=-1,
                keepdim=True
            )
        )


        outputs = (
            classifier(
                embeddings
            )
        )


        loss = criterion(
            outputs,
            labels
        )


        loss.backward()


        torch.nn.utils.clip_grad_norm_(
            list(
                classifier.parameters()
            )
            +
            bioclip_trainable_parameters,
            max_norm=1.0
        )


        optimizer.step()


        train_loss += (
            loss.item()
            * images.size(0)
        )


        predictions = (
            outputs.argmax(
                dim=1
            )
        )


        train_correct += (
            predictions
            == labels
        ).sum().item()


        train_total += (
            labels.size(0)
        )


    train_loss /= (
        train_total
    )

    train_accuracy = (
        train_correct
        / train_total
    )


    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    bioclip.eval()
    classifier.eval()

    val_loss = 0.0
    val_correct = 0
    val_total = 0


    with torch.no_grad():

        for images, labels in val_loader:

            images = images.to(
                device
            )

            labels = labels.to(
                device
            )


            embeddings = (
                bioclip.encode_image(
                    images
                )
            )


            embeddings = (
                embeddings
                / embeddings.norm(
                    dim=-1,
                    keepdim=True
                )
            )


            outputs = (
                classifier(
                    embeddings
                )
            )


            loss = criterion(
                outputs,
                labels
            )


            val_loss += (
                loss.item()
                * images.size(0)
            )


            predictions = (
                outputs.argmax(
                    dim=1
                )
            )


            val_correct += (
                predictions
                == labels
            ).sum().item()


            val_total += (
                labels.size(0)
            )


    val_loss /= (
        val_total
    )

    val_accuracy = (
        val_correct
        / val_total
    )


    scheduler.step(
        val_accuracy
    )


    # --------------------------------------------------------
    # SAVE BEST
    # --------------------------------------------------------

    if (
        val_accuracy
        > best_validation_accuracy
    ):

        best_validation_accuracy = (
            val_accuracy
        )

        best_checkpoint = {

            "bioclip_state_dict":
                copy.deepcopy(
                    bioclip.state_dict()
                ),

            "classifier_state_dict":
                copy.deepcopy(
                    classifier.state_dict()
                ),

            "classes":
                train_dataset.classes,

            "class_to_idx":
                train_dataset.class_to_idx,

            "embedding_dimension":
                embedding_dimension,

            "model_name":
                MODEL_NAME,

            "best_validation_accuracy":
                best_validation_accuracy,

        }


    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    print()
    print(
        f"Epoch "
        f"{epoch:02d}/{EPOCHS}"
    )

    print(
        f"Train Loss: "
        f"{train_loss:.4f}"
    )

    print(
        f"Train Accuracy: "
        f"{train_accuracy * 100:.2f}%"
    )

    print(
        f"Validation Loss: "
        f"{val_loss:.4f}"
    )

    print(
        f"Validation Accuracy: "
        f"{val_accuracy * 100:.2f}%"
    )


# ============================================================
# SAVE
# ============================================================

if best_checkpoint is None:

    raise RuntimeError(
        "No valid checkpoint "
        "was created."
    )


torch.save(
    best_checkpoint,
    MODEL_OUTPUT
)


print()
print("=" * 70)
print("FINE-TUNING COMPLETE")
print("=" * 70)

print(
    f"Best validation accuracy: "
    f"{best_validation_accuracy * 100:.2f}%"
)

print(
    f"Saved model to:\n"
    f"{MODEL_OUTPUT}"
)