from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RecognizedLine:
    line_number: int
    text: str
    confidence: float | None = None
    bounding_box: tuple[int, int, int, int] | None = None


@dataclass
class HTRResult:
    full_text: str
    lines: list[RecognizedLine]
    average_confidence: float | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
