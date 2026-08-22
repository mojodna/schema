"""Typed record of everything the Vecorel emit could not carry.

The bead asks for "a documented, raised exception rather than a silent
omission". A renderer that raises on the first one cannot produce a census,
so the renderer collects these and `strict=True` turns the collection into
a raise. Both directions are the finding, which is why `kind` distinguishes
them: an IR gap is a statement about the codegen IR, a target gap is a
statement about Vecorel SDL, and confusing the two would overstate either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["Kind", "VecorelGap", "VecorelUnrepresentable"]

Kind = Literal["ir-gap", "target-gap", "target-dialect", "renderer-gap"]


@dataclass(frozen=True, slots=True)
class VecorelGap:
    """One capability that did not survive the emit.

    `path` is a JSON-pointer-ish location in the emitted document, `capability`
    names what was lost in the vocabulary of whichever side owns the loss, and
    `detail` carries the mechanism -- classification is by mechanism, not by
    keyword, the same rule the JSON Schema census settled on.
    """

    model: str
    path: str
    kind: Kind
    capability: str
    detail: str


class VecorelUnrepresentable(Exception):
    """Raised in strict mode, or when a document cannot be emitted at all."""

    def __init__(self, gaps: tuple[VecorelGap, ...]) -> None:
        self.gaps = gaps
        head = gaps[0]
        super().__init__(
            f"{head.model}{head.path}: {head.capability} ({head.kind}) -- {head.detail}"
            + (f" [+{len(gaps) - 1} more]" if len(gaps) > 1 else "")
        )
