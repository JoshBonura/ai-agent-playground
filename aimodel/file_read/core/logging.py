# aimodel/core/logging.py
from __future__ import annotations

import logging
import sys

# request_ctx lives in the same package
try:
    from . import request_ctx  # aimodel/core/request_ctx.py
except Exception:
    request_ctx = None


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        xid = ""
        sid = ""
        try:
            if request_ctx is not None:
                xid = (request_ctx.get_x_id() or "").strip()
                # If you add session id to request_ctx later, wire it here.
                # sid = (request_ctx.get_session_id() or "").strip()
        except Exception:
            pass
        record.xid = xid
        record.sid = sid
        return True


def _default_formatter() -> logging.Formatter:
    fmt = "%(asctime)s %(levelname)s %(name)s xid=%(xid)s sid=%(sid)s: %(message)s"
    return logging.Formatter(fmt)


def setup_logging(level: int = logging.INFO, *, json: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(level)

    # ensure a single stdout handler exists (uvicorn may add one)
    stream = None
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler):
            stream = h
            break
    if stream is None:
        stream = logging.StreamHandler(sys.stdout)
        root.addHandler(stream)

    # always apply our formatter + context filter (don’t bail early)
    stream.setFormatter(_default_formatter())
    if not any(isinstance(f, ContextFilter) for f in stream.filters):
        stream.addFilter(ContextFilter())

    # keep uvicorn loggers at same level so our logs aren’t hidden
    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)


def get_logger(name: str | None = None) -> logging.Logger:
    lg = logging.getLogger(name or __name__)
    lg.propagate = True
    lg.setLevel(logging.NOTSET)
    return lg
