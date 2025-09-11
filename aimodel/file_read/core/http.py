# aimodel/file_read/web/http.py
from __future__ import annotations

import json
from typing import Any

import httpx

from ..core.logging import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(connect=2.0, read=10.0, write=2.0, pool=2.0)
DEFAULT_LIMITS = httpx.Limits(max_keepalive_connections=20, max_connections=40)


class ExternalServiceError(RuntimeError):
    def __init__(
        self,
        *,
        service: str,
        url: str,
        status: int | None = None,
        body_preview: str | None = None,
        detail: str | None = None,
    ) -> None:
        msg = f"{service} request failed status={status} url={url}"
        if detail:
            msg += f" detail={detail}"
        super().__init__(msg)
        self.service = service
        self.url = url
        self.status = status
        self.body_preview = body_preview
        self.detail = detail


# a single shared async client (uvicorn lifespan keeps it around)
_async_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=DEFAULT_LIMITS,
            follow_redirects=False,
        )
    return _async_client


async def arequest_json(
    *,
    method: str,
    url: str,
    service: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: httpx.Timeout | None = None,
) -> dict[str, Any]:
    """Make an async request that:
    - sets sane timeouts,
    - raises for non-2xx,
    - returns parsed JSON,
    - logs structured events,
    - throws ExternalServiceError on failure.
    """
    client = await get_client()
    try:
        resp = await client.request(
            method.upper(),
            url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=timeout or DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()

        ctype = (resp.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            return resp.json()
        # best-effort JSON parse, else wrap as {"text": "..."}
        try:
            return json.loads(resp.text)
        except Exception:
            return {"text": resp.text}

    except httpx.HTTPStatusError as e:
        body_preview = (e.response.text or "")[:400] if e.response is not None else None
        log.warning(
            "http_status_error",
            extra={
                "service": service,
                "url": url,
                "status": e.response.status_code if e.response else None,
                "body_preview": body_preview,
            },
        )
        raise ExternalServiceError(
            service=service,
            url=url,
            status=e.response.status_code if e.response else None,
            body_preview=body_preview,
            detail=str(e),
        ) from e

    except httpx.TimeoutException as e:
        log.warning("http_timeout", extra={"service": service, "url": url})
        raise ExternalServiceError(service=service, url=url, detail="timeout") from e

    except httpx.RequestError as e:
        log.error("http_request_error", extra={"service": service, "url": url, "detail": str(e)})
        raise ExternalServiceError(service=service, url=url, detail=str(e)) from e
