from __future__ import annotations

from typing import Any

import numpy as np

from .result import RecognizedLine


class HandwritingRecognizer:
    """Lazy-loading line recognizer backed by a configurable Hugging Face model."""

    def __init__(self, model_name: str = "microsoft/trocr-base-handwritten", device: str | None = None, processor: Any | None = None, model: Any | None = None) -> None:
        self.model_name, self._device_name = model_name, device
        self.processor, self.model = processor, model

    @property
    def device(self) -> str:
        if self._device_name is None:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        return self._device_name

    def _load_model(self) -> None:
        if self.processor is not None and self.model is not None:
            return
        try:
            import torch
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        except ImportError as error:
            raise RuntimeError("HTR recognition requires torch, transformers, and Pillow. Install requirements-htr.txt in a Python 3.13 environment.") from error
        self.processor = TrOCRProcessor.from_pretrained(self.model_name)
        self.model = VisionEncoderDecoderModel.from_pretrained(self.model_name)
        self.model.to(self.device)
        self.model.eval()

    def recognize(self, line_image: np.ndarray, line_number: int = 1, bounding_box: tuple[int, int, int, int] | None = None) -> RecognizedLine:
        self._load_model()
        from PIL import Image
        if not isinstance(line_image, np.ndarray) or line_image.size == 0:
            raise ValueError("Line image must be a non-empty numpy array")
        if line_image.ndim == 2:
            line_image = np.repeat(line_image[:, :, None], 3, axis=2)
        image = Image.fromarray(line_image[:, :, :3].astype(np.uint8)).convert("RGB")
        inputs = self.processor(images=image, return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        outputs = self.model.generate(**inputs, output_scores=True, return_dict_in_generate=True)
        text = self.processor.batch_decode(outputs.sequences, skip_special_tokens=True)[0].strip()
        confidence = self._confidence(outputs)
        return RecognizedLine(line_number, text, confidence, bounding_box)

    def _confidence(self, outputs: Any) -> float | None:
        if not getattr(outputs, "scores", None):
            return None
        transition_scores = self.model.compute_transition_scores(outputs.sequences, outputs.scores, normalize_logits=True)
        scores = transition_scores[0]
        if scores.numel() == 0:
            return None
        return float(np.exp(scores.detach().cpu().numpy().mean()))
