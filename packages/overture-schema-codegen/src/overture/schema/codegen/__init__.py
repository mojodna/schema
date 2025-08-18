"""Code generation tools for Overture Maps schemas.

This package provides tools for generating code from Pydantic models,
with initial focus on Spark-compatible Scala code generation.
"""

from overture.schema.codegen.__about__ import __version__
from overture.schema.codegen.markdown import SortOrder

__all__ = ["__version__", "SortOrder"]
