# aimodel/file_read/telemetry/models.py
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PackTel(BaseModel):
    # Timings
    packSec: float = 0.0
    summarySec: float = 0.0
    finalTrimSec: float = 0.0
    compressSec: float = 0.0

    # Summary metrics
    summaryTokensApprox: int = 0
    summaryUsedLLM: bool = False
    summaryBullets: int = 0
    summaryAddedChars: int = 0
    summaryOutTokensApprox: int = 0
    summaryCompressedFromChars: int = 0
    summaryCompressedToChars: int = 0
    summaryCompressedDroppedChars: int = 0

    # Packing metrics
    packInputTokensApprox: int = 0
    packMsgs: int = 0

    # Final trim metrics
    finalTrimTokensBefore: int = 0
    finalTrimTokensAfter: int = 0
    finalTrimDroppedMsgs: int = 0
    finalTrimDroppedApproxTokens: int = 0
    finalTrimSummaryShrunkFromChars: int = 0
    finalTrimSummaryShrunkToChars: int = 0
    finalTrimSummaryDroppedChars: int = 0

    # Rolling summary metrics
    rollStartTokens: int = 0
    rollOverageTokens: int = 0
    rollPeeledMsgs: int = 0
    rollNewSummaryChars: int = 0
    rollNewSummaryTokensApprox: int = 0
    rollEndTokens: int = 0

    # Compatibility flag (used by pipeline)
    ignore_ephemeral_in_summary: bool = False

    # ---- Compatibility helpers ----
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def update_from(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def reset(self) -> None:
        for name, field in self.model_fields.items():
            setattr(self, name, field.default)
