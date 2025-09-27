from __future__ import annotations

from ..core.logging import get_logger

log = get_logger(__name__)
from typing import Any

from ..core.packing_ops import (build_system, pack_messages,
                                roll_summary_if_needed)
from ..core.settings import SETTINGS
from ..rag.retrieve_pipeline import (
    build_rag_block_session_only_with_telemetry,
    build_rag_block_with_telemetry)


def build_system_text() -> str:
    eff = SETTINGS.effective()
    base = build_system(
        style=str(eff["pack_style"]),
        short=bool(eff["pack_short"]),
        bullets=bool(eff["pack_bullets"]),
    )
    guidance = str(eff["packing_guidance"])
    return base + guidance


def pack_with_rollup(
    *,
    system_text: str,
    summary: str,
    recent,
    max_ctx: int,
    out_budget: int,
    ephemeral: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, str]], str, int]:
    eff = SETTINGS.effective()
    packed, input_budget = pack_messages(
        style=str(eff["pack_style"]),
        short=bool(eff["pack_short"]),
        bullets=bool(eff["pack_bullets"]),
        summary=summary,
        recent=recent,
        max_ctx=max_ctx,
        out_budget=out_budget,
    )
    packed, new_summary = roll_summary_if_needed(
        packed=packed,
        recent=recent,
        summary=summary,
        input_budget=input_budget,
        system_text=system_text,
    )
    if ephemeral:
        last_user_idx = None
        for i in range(len(packed) - 1, -1, -1):
            m = packed[i]
            if isinstance(m, dict) and m.get("role") == "user":
                last_user_idx = i
                break
        eph = list(ephemeral)
        if last_user_idx is not None:
            packed = packed[:last_user_idx] + eph + packed[last_user_idx:]
        else:
            packed = packed + eph
    return (packed, new_summary, input_budget)


def maybe_inject_rag_block(
    messages: list[dict],
    *,
    session_id: str | None,
    skip_rag: bool = False,
    rag_query: str | None = None,
    force_session_only: bool = False,
) -> tuple[list[dict], dict[str, Any] | None, str | None]:
    if skip_rag:
        return (messages, None, None)
    if not SETTINGS.get("rag_enabled", True):
        return (messages, None, None)
    if not messages or messages[-1].get("role") != "user":
        return (messages, None, None)

    user_q = rag_query or (messages[-1].get("content") or "")
    use_session_only = force_session_only or not SETTINGS.get("rag_global_enabled", True)

    if use_session_only and SETTINGS.get("rag_session_enabled", True):
        block, tel = build_rag_block_session_only_with_telemetry(user_q, session_id=session_id)
        mode = "session-only"
    else:
        block, tel = build_rag_block_with_telemetry(user_q, session_id=session_id)
        mode = "global"

    if not block:
        log.debug(f"[RAG INJECT] no hits (session={session_id}) q={user_q!r}")
        return (messages, None, None)

    log.debug(f"[RAG INJECT] injecting (session={session_id}) chars={len(block)} mode={mode}")
    injected = messages[:-1] + [{"role": "user", "content": block}, messages[-1]]

    tel = dict(tel or {})
    tel["injected"] = True
    tel["mode"] = mode
    return (injected, tel, block)
