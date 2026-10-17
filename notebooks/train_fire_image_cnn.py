"""Train and evaluate a small fire/non-fire image classifier.

Expected input folders: data/fire_images/{train,val,test}/{fire,no_fire}/.
The dataset itself is not bundled with this repository.
"""

import argparse
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from backend.services.fire_image_model import FireImageCNN


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_SIZE = 128


def class_indices(classes):
    normalized = {name: name.lower().replace(" ", "_").replace("-", "_") for name in classes}
    fire_names = [name for name, value in normalized.items()
                  if "fire" in value and not any(x in value for x in ("no_fire", "nonfire", "non_fire"))]
    other_names = [name for name in classes if name not in fire_names]
    if len(classes) != 2 or len(fire_names) != 1 or len(other_names) != 1:
        raise ValueError("Each split must have exactly two class folders: fire and no_fire (or equivalent).")
    return classes.index(fire_names[0]), classes.index(other_names[0])


def evaluate(model, loader, device, fire_index):
    model.eval()
    correct = total = fire_true_positive = fire_actual = fire_predicted = 0
    with torch.no_grad():
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            predictions = model(images).argmax(dim=1)
            correct += (predictions == labels).sum().item()
            total += labels.size(0)
            fire_true_positive += ((predictions == fire_index) & (labels == fire_index)).sum().item()
            fire_actual += (labels == fire_index).sum().item()
            fire_predicted += (predictions == fire_index).sum().item()
    return {
        "accuracy": correct / max(total, 1),
        "fire_recall": fire_true_positive / max(fire_actual, 1),
        "fire_precision": fire_true_positive / max(fire_predicted, 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "fire_images")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    transform = transforms.Compose([
        transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])
    datasets_by_split = {
        split: datasets.ImageFolder(args.data_dir / split, transform=transform)
        for split in ("train", "val", "test")
    }
    classes = datasets_by_split["train"].classes
    fire_index, _ = class_indices(classes)
    for split, dataset in datasets_by_split.items():
        if dataset.classes != classes:
            raise ValueError(f"Class folders differ in the {split} split.")

    loaders = {
        split: DataLoader(dataset, batch_size=args.batch_size, shuffle=(split == "train"))
        for split, dataset in datasets_by_split.items()
    }
    model = FireImageCNN(num_classes=len(classes)).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    model_path = PROJECT_ROOT / "models" / "fire_image_cnn.pth"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    best_val_accuracy = -1.0

    for epoch in range(args.epochs):
        model.train()
        running_loss = 0.0
        for images, labels in loaders["train"]:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()

        validation = evaluate(model, loaders["val"], device, fire_index)
        mean_loss = running_loss / max(len(loaders["train"]), 1)
        print(f"Epoch {epoch + 1}/{args.epochs} - loss {mean_loss:.4f} - validation accuracy {validation['accuracy']:.3f}")
        if validation["accuracy"] > best_val_accuracy:
            best_val_accuracy = validation["accuracy"]
            torch.save({"state_dict": model.cpu().state_dict(), "classes": classes}, model_path)
            model.to(device)

    checkpoint = torch.load(model_path, map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    test_metrics = evaluate(model, loaders["test"], device, fire_index)
    print("Held-out test results:")
    print(f"  Accuracy:     {test_metrics['accuracy']:.3f}")
    print(f"  Fire recall:  {test_metrics['fire_recall']:.3f}")
    print(f"  Fire precision: {test_metrics['fire_precision']:.3f}")
    print(f"Saved best-validation checkpoint to {model_path}")


if __name__ == "__main__":
    main()
