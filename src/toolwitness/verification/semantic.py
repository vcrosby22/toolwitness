"""Semantic verification — post-MVP stub.

Will support embedding-based comparison between tool output and agent claims.
Extras: toolwitness[semantic] (local ONNX) or toolwitness[openai] (API embeddings).
"""

from __future__ import annotations


def semantic_similarity(text_a: str, text_b: str) -> float:
    """Placeholder for semantic similarity scoring.

    Returns 0.0 until a verification backend is installed.
    """
    raise NotImplementedError(
        "Semantic verification requires an optional extra: "
        "pip install toolwitness[semantic] or toolwitness[openai]"
    )
