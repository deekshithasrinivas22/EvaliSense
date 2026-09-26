from .line_segmenter import HandwritingLineSegmenter, LineRegion
from .recognizer import HandwritingRecognizer
from .result import HTRResult, RecognizedLine


def __getattr__(name: str):
	if name == "HTRPipeline":
		from .pipeline import HTRPipeline

		return HTRPipeline
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
	"HTRPipeline",
	"HTRResult",
	"HandwritingLineSegmenter",
	"HandwritingRecognizer",
	"LineRegion",
	"RecognizedLine",
]
"""Handwritten Text Recognition package for EvaliSense."""
