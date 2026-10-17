"""Optional local inference for a trained fire/non-fire image CNN."""

from io import BytesIO

from backend.config import settings


class FireImageService:
    def __init__(self):
        self.model_path = settings.BASE_DIR / "models" / "fire_image_cnn.pth"

    def status(self):
        return {
            "available": self.model_path.is_file(),
            "message": "Trained fire-image model is ready." if self.model_path.is_file()
            else "No trained fire-image model found. Prepare the dataset and run the training script first.",
        }

    def predict(self, image_bytes):
        if not self.model_path.is_file():
            raise RuntimeError("Fire-image model is not trained. Follow the training instructions in README.md.")

        try:
            import torch
            from PIL import Image
            from torchvision import transforms
            from backend.services.fire_image_model import FireImageCNN
        except ImportError as exc:
            raise RuntimeError("Install requirements-fire-image.txt to use image review.") from exc

        try:
            image = Image.open(BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise ValueError("The uploaded file is not a readable image.") from exc

        checkpoint = torch.load(self.model_path, map_location="cpu", weights_only=True)
        classes = checkpoint["classes"]
        model = FireImageCNN(num_classes=len(classes))
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()

        transform = transforms.Compose([
            transforms.Resize((128, 128)),
            transforms.ToTensor(),
            transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
        ])
        with torch.no_grad():
            scores = torch.softmax(model(transform(image).unsqueeze(0)), dim=1)[0]

        predicted_index = int(scores.argmax().item())
        predicted_class = classes[predicted_index]
        normalized_class = predicted_class.lower().replace("-", "_").replace(" ", "_")
        is_fire = "fire" in normalized_class and not any(
            token in normalized_class for token in ("no_fire", "nofire", "nonfire", "non_fire")
        )
        return {
            "label": "Fire-like image" if is_fire else "No fire-like image",
            "class_name": predicted_class,
            "score": round(float(scores[predicted_index].item()), 4),
            "class_scores": {name: round(float(scores[i].item()), 4) for i, name in enumerate(classes)},
            "note": "Model score is not calibrated. Review the image manually; this result is not an emergency alert.",
        }


fire_image_service = FireImageService()
