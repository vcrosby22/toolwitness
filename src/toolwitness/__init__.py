"""ToolWitness — detect when AI agents skip tools or fabricate outputs."""

from toolwitness._version import __version__
from toolwitness.core.detector import ToolWitnessDetector
from toolwitness.core.types import (
    Classification,
    ExecutionReceipt,
    Handoff,
    HandoffVerificationResult,
    VerificationResult,
)

__all__ = [
    "__version__",
    "Classification",
    "ExecutionReceipt",
    "Handoff",
    "HandoffVerificationResult",
    "ToolWitnessDetector",
    "VerificationResult",
]
