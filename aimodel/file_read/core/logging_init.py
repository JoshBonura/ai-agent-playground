# aimodel/file_read/core/logging_init.py
from __future__ import annotations
import logging, sys

def init_logging(level: int = logging.INFO) -> None:
    # Root + uvicorn
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
    )
    # Make sure our module loggers show up
    logging.getLogger("aimodel").setLevel(level)
    logging.getLogger("aimodel.api.generate").setLevel(level)

    # Capture C++ backend prints (llama_perf_context_print) from stderr
    class _StderrToLogger:
        def __init__(self, logger: logging.Logger) -> None:
            self._logger = logger
        def write(self, msg: str) -> None:
            msg = (msg or "").rstrip()
            if msg:
                # Use INFO to avoid dropping at default Uvicorn levels
                self._logger.info(msg)
        def flush(self) -> None:
            pass

    sys.stderr = _StderrToLogger(logging.getLogger("llama_cpp.stderr"))
