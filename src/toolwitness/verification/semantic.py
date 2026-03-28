"""Semantic verification — post-MVP (EP-05 / ST-30).

Not yet implemented. Will support embedding-based comparison between
tool output and agent claims to handle unit conversion, summarization,
and natural-language paraphrasing that structural matching cannot resolve.

Planned extras:
  - toolwitness[semantic] — local ONNX model (no API calls)
  - toolwitness[openai]   — OpenAI embeddings API

Tracked in backlog: ST-30 (Semantic verification via embeddings).
Related bugs: BUG-01 (unit conversion), BUG-02 (list summarization).
"""

from __future__ import annotations


def semantic_similarity(text_a: str, text_b: str) -> float:
    """Compare two texts semantically. Not yet implemented.

    Raises NotImplementedError until a verification backend is available.
    """
    raise NotImplementedError(
        "Semantic verification is not yet implemented (post-MVP). "
        "Track progress: https://github.com/vcrosby22/toolwitness "
        "— Epic EP-05, Story ST-30."
    )
