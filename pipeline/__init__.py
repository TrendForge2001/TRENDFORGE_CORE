"""Legacy pipeline compatibility surface.

Canonical scanner execution lives in scanner.FullScannerPipeline and
engines.EngineOrchestrator. The exports here are compatibility facades only.
"""

from .engine_registry import EngineRegistry
from .result_aggregator import ResultAggregator
from .scan_pipeline import ScanPipeline

__all__ = ["EngineRegistry", "ResultAggregator", "ScanPipeline"]
