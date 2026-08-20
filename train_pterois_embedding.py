from pathlib import Path
import copy

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
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
EPOCHS = 15
LEARNING_RATE = 1e-3

OUTPUT_DIR = Path("models")
OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

MODEL_OUTPUT = (
    OUTPUT_DIR
    / "pterois_bioclip_classifier.pt"
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
print("PTEROIS BIOCLIP TRAINING")
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
bioclip.eval()


# ============================================================
# FREEZE BIOCLIP
# ============================================================

for parameter in bioclip.parameters():
    parameter.requires_grad = False


print("BioCLIP backbone frozen.")


# ============================================================
# DATASETS
# ============================================================

train_dataset = ImageFolder(
    TRAIN_DIR,
    transform=preprocess
)

val_dataset = ImageFolder(
    VAL_DIR,
    transform=preprocess
)


print("\nClasses:")

for class_name, index in (
    train_dataset.class_to_idx.items()
):
    print(
        f"  {index}: {class_name}"
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
)

val_loader = DataLoader(
    val_dataset,
    batch_size=BATCH_SIZE,
    shuffle=False,
)


# ============================================================
# FIND EMBEDDING DIMENSION
# ============================================================

sample_images, _ = next(
    iter(train_loader)
)

sample_images = sample_images.to(
    device
)

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
    f"\nBioCLIP embedding dimension: "
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
        0.30
    ),

    nn.Linear(
        256,
        len(
            train_dataset.classes
        )
    )

).to(device)


# ============================================================
# LOSS + OPTIMIZER
# ============================================================

criterion = (
    nn.CrossEntropyLoss()
)

optimizer = torch.optim.Adam(
    classifier.parameters(),
    lr=LEARNING_RATE
)


# ============================================================
# TRAINING
# ============================================================

best_validation_accuracy = 0.0
best_classifier_state = None


for epoch in range(
    1,
    EPOCHS + 1
):

    # --------------------------------------------------------
    # TRAIN
    # --------------------------------------------------------

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


        # BioCLIP stays frozen.

        with torch.no_grad():

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


        optimizer.zero_grad()


        outputs = classifier(
            embeddings
        )


        loss = criterion(
            outputs,
            labels
        )


        loss.backward()

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


            outputs = classifier(
                embeddings
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

        best_classifier_state = (
            copy.deepcopy(
                classifier.state_dict()
            )
        )


    # --------------------------------------------------------
    # PRINT EPOCH
    # --------------------------------------------------------

    print(
        f"\nEpoch "
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
# SAVE BEST MODEL
# ============================================================

if best_classifier_state is None:

    raise RuntimeError(
        "Training failed to produce "
        "a valid classifier."
    )


checkpoint = {

    "classifier_state_dict":
        best_classifier_state,

    "embedding_dimension":
        embedding_dimension,

    "classes":
        train_dataset.classes,

    "class_to_idx":
        train_dataset.class_to_idx,

    "model_name":
        MODEL_NAME,

    "best_validation_accuracy":
        best_validation_accuracy,
}


torch.save(
    checkpoint,
    MODEL_OUTPUT
)


print()
print("=" * 70)
print("TRAINING COMPLETE")
print("=" * 70)

print(
    f"Best validation accuracy: "
    f"{best_validation_accuracy * 100:.2f}%"
)

print(
    f"Saved model to:\n"
    f"{MODEL_OUTPUT}"
)