from __future__ import annotations

from threading import Lock
from typing import Any

import numpy as np

from .result import RecognizedLine


class HandwritingRecognizer:
    """Cached, inference-only TrOCR recognition with small line batches."""

    def __init__(self, model_name: str = 'microsoft/trocr-base-handwritten', device: str | None = None,
                 processor: Any | None = None, model: Any | None = None, batch_size: int | None = None) -> None:
        self.model_name, self._device_name = model_name, device
        self.processor, self.model = processor, model
        self.batch_size = batch_size
        self._load_lock = Lock()
        self._inference_lock = Lock()

    @property
    def device(self) -> str:
        if self._device_name is None:
            import torch
            self._device_name = 'cuda' if torch.cuda.is_available() else 'cpu'
        return self._device_name

    @staticmethod
    def _from_cache_or_download(factory, name):
        # A complete cached model needs no online metadata check on first use.
        try:
            return factory.from_pretrained(name, local_files_only=True)
        except OSError:
            return factory.from_pretrained(name)

    def _load_model(self) -> None:
        with self._load_lock:
            if self.processor is not None and self.model is not None:
                return
            try:
                import torch
                from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            except ImportError as error:
                raise RuntimeError('TrOCR needs torch, transformers and Pillow in the Python environment running this server.') from error
            processor = self._from_cache_or_download(TrOCRProcessor, self.model_name)
            model = self._from_cache_or_download(VisionEncoderDecoderModel, self.model_name)
            model.to(self.device)
            model.eval()
            # Publish only a fully loaded model, so a failed load remains retryable.
            self.processor, self.model = processor, model

    @staticmethod
    def _pil_image(line_image):
        from PIL import Image
        if not isinstance(line_image, np.ndarray) or line_image.size == 0:
            raise ValueError('Line image must be a non-empty numpy array')
        if line_image.ndim == 2:
            return Image.fromarray(line_image.astype(np.uint8)).convert('RGB')
        if line_image.ndim != 3 or line_image.shape[2] not in (1, 3, 4):
            raise ValueError('Line image must be grayscale, BGR or BGRA')
        if line_image.shape[2] == 1:
            return Image.fromarray(line_image[:, :, 0].astype(np.uint8)).convert('RGB')
        # OpenCV images are BGR, whereas PIL/TrOCR expects RGB.
        return Image.fromarray(line_image[:, :, :3][:, :, ::-1].astype(np.uint8)).convert('RGB')

    def recognize_batch(self, line_images, line_numbers=None, bounding_boxes=None) -> list[RecognizedLine]:
        images = list(line_images)
        if not images:
            return []
        numbers = list(line_numbers) if line_numbers is not None else list(range(1, len(images) + 1))
        boxes = list(bounding_boxes) if bounding_boxes is not None else [None] * len(images)
        if len(numbers) != len(images) or len(boxes) != len(images):
            raise ValueError('Image, line-number and bounding-box counts must agree')
        pil_images = [self._pil_image(image) for image in images]
        self._load_model()
        import torch
        batch_size = self.batch_size or (4 if self.device.startswith('cuda') else 2)
        if batch_size < 1:
            raise ValueError('Batch size must be positive')
        lines = []
        # Serialize inference on the shared model; concurrent clicks cannot exhaust memory.
        with self._inference_lock, torch.inference_mode():
            for start in range(0, len(pil_images), batch_size):
                inputs = self.processor(images=pil_images[start:start + batch_size], return_tensors='pt')
                inputs = {key: value.to(self.device) for key, value in inputs.items()}
                # The cached TrOCR generation config disables KV caching. Turn it on
                # explicitly without lowering beam count, resolution or token limits.
                outputs = self.model.generate(**inputs, use_cache=True, output_scores=True, return_dict_in_generate=True)
                texts = self.processor.batch_decode(outputs.sequences, skip_special_tokens=True)
                confidences = self._confidences(outputs)
                for index, text in enumerate(texts):
                    absolute = start + index
                    lines.append(RecognizedLine(numbers[absolute], text.strip(), confidences[index], boxes[absolute]))
        return lines

    def recognize(self, line_image: np.ndarray, line_number: int = 1,
                  bounding_box: tuple[int, int, int, int] | None = None) -> RecognizedLine:
        return self.recognize_batch([line_image], [line_number], [bounding_box])[0]

    def _confidences(self, outputs: Any) -> list[float | None]:
        count = len(outputs.sequences)
        if not getattr(outputs, 'scores', None):
            return [None] * count
        kwargs = {'normalize_logits': True}
        if getattr(outputs, 'beam_indices', None) is not None:
            kwargs['beam_indices'] = outputs.beam_indices
        transition = self.model.compute_transition_scores(outputs.sequences, outputs.scores, **kwargs)
        config = self.model.generation_config
        pad_id = getattr(config, 'pad_token_id', None)
        eos_ids = getattr(config, 'eos_token_id', None)
        eos_ids = {eos_ids} if isinstance(eos_ids, int) else set(eos_ids or [])
        values = []
        for row, scores in enumerate(transition):
            if scores.numel() == 0:
                values.append(None)
                continue
            tokens = outputs.sequences[row, -scores.shape[0]:].detach().cpu().tolist()
            selected = []
            probabilities = scores.detach().cpu().numpy()
            for token, score in zip(tokens, probabilities):
                if token != pad_id or token in eos_ids:
                    selected.append(float(score))
                if token in eos_ids:
                    break
            values.append(float(np.exp(np.mean(selected))) if selected else None)
        return values

    def _confidence(self, outputs: Any) -> float | None:
        """Compatibility for callers requesting one recognized line."""
        return self._confidences(outputs)[0]
