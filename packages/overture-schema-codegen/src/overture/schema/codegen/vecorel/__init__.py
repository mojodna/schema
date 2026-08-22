"""Vecorel SDL rendering from the codegen extraction IR (spike)."""

from .exceptions import VecorelGap, VecorelUnrepresentable
from .pipeline import VecorelOutput, generate_vecorel_documents
from .renderer import SDL_SCHEMA_URI, VecorelDocument, render_vecorel

__all__ = [
    "SDL_SCHEMA_URI",
    "VecorelDocument",
    "VecorelGap",
    "VecorelOutput",
    "VecorelUnrepresentable",
    "generate_vecorel_documents",
    "render_vecorel",
]
