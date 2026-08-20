from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder
import open_clip


# ============================================================
# CONFIG
# ============================================================

TEST_DIR = Path(
    "data/pterois_dataset/split/test"
)

CHECKPOINT_PATH = Path(
    "models/pterois_bioclip_finetuned.pt"
)

BATCH_SIZE = 8


# ============================================================
# DEVICE
# ============================================================

device = torch.device(
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
)

print("=" * 70)
print("PTEROIS FINE-TUNED MODEL EVALUATION")
print("=" * 70)

print(f"Device: {device}")


# ============================================================
# LOAD CHECKPOINT
# ============================================================

checkpoint = torch.load(
    CHECKPOINT_PATH,
    map_location=device,
    weights_only=False
)

MODEL_NAME = checkpoint["model_name"]
classes = checkpoint["classes"]

embedding_dimension = checkpoint[
    "embedding_dimension"
]

print("\nClasses:")

for index, name in enumerate(classes):
    print(f"  {index}: {name}")


# ============================================================
# LOAD BIOCLIP
# ============================================================

print("\nLoading BioCLIP 2...")

bioclip, _, preprocess = (
    open_clip.create_model_and_transforms(
        MODEL_NAME
    )
)

bioclip.load_state_dict(
    checkpoint["bioclip_state_dict"]
)

bioclip = bioclip.to(device)
bioclip.eval()


# ============================================================
# RECREATE CLASSIFIER
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
        len(classes)
    )

).to(device)


classifier.load_state_dict(
    checkpoint["classifier_state_dict"]
)

classifier.eval()


# ============================================================
# TEST DATA
# ============================================================

test_dataset = ImageFolder(
    TEST_DIR,
    transform=preprocess
)

test_loader = DataLoader(
    test_dataset,
    batch_size=BATCH_SIZE,
    shuffle=False,
    num_workers=0
)

print(
    f"\nTest images: "
    f"{len(test_dataset)}"
)


# ============================================================
# EVALUATION
# ============================================================

correct = 0
total = 0

class_correct = {
    name: 0
    for name in classes
}

class_total = {
    name: 0
    for name in classes
}

wrong_predictions = []


with torch.no_grad():

    for images, labels in test_loader:

        images = images.to(device)
        labels = labels.to(device)

        embeddings = bioclip.encode_image(
            images
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

        probabilities = torch.softmax(
            outputs,
            dim=1
        )

        confidence, predictions = (
            probabilities.max(dim=1)
        )


        for i in range(
            labels.size(0)
        ):

            expected_index = (
                labels[i].item()
            )

            predicted_index = (
                predictions[i].item()
            )

            expected = classes[
                expected_index
            ]

            predicted = classes[
                predicted_index
            ]

            conf = confidence[
                i
            ].item()


            class_total[
                expected
            ] += 1


            if (
                expected_index
                == predicted_index
            ):

                correct += 1

                class_correct[
                    expected
                ] += 1

            else:

                wrong_predictions.append({
                    "expected": expected,
                    "predicted": predicted,
                    "confidence": conf,
                })


            total += 1


# ============================================================
# RESULTS
# ============================================================

accuracy = (
    correct / total
    if total
    else 0
)


print()
print("=" * 70)
print("TEST RESULTS")
print("=" * 70)

print(
    f"Overall: "
    f"{correct}/{total}"
)

print(
    f"Accuracy: "
    f"{accuracy * 100:.2f}%"
)


print("\nPER-SPECIES ACCURACY")


for species in classes:

    species_total = (
        class_total[species]
    )

    species_correct = (
        class_correct[species]
    )

    species_accuracy = (
        species_correct
        / species_total
        if species_total
        else 0
    )

    print(
        f"{species:<25} "
        f"{species_correct}/"
        f"{species_total} "
        f"({species_accuracy * 100:.2f}%)"
    )


print("\nWRONG PREDICTIONS")


if not wrong_predictions:

    print("None.")

else:

    for item in wrong_predictions:

        print(
            f"Expected: "
            f"{item['expected']:<20} "
            f"Predicted: "
            f"{item['predicted']:<20} "
            f"Confidence: "
            f"{item['confidence']:.4f}"
        )