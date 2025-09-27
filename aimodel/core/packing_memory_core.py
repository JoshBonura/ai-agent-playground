from __future__ import annotations

import math
import time
from collections import deque

from ..core.logging import get_logger

log = get_logger(__name__)

from ..core.settings import SETTINGS
from ..runtime.model_runtime import get_llm
from ..store import get_summary as store_get_summary
from ..store import list_messages as store_list_messages
from ..telemetry.models import PackTel
from ..utils.streaming import strip_runjson
from .style import get_style_sys

SESSIONS: dict[str, dict] = {}
PACK_TELEMETRY = PackTel()
SUMMARY_TEL = PACK_TELEMETRY


def _S() -> dict:
    """Convenience accessor for effective settings."""
    return SETTINGS.effective()


def approx_tokens(text: str) -> int:
    cfg = _S()
    chars_per_token = int(cfg.get("chars_per_token", 4))
    return max(1, math.ceil(len(text or "") / chars_per_token))


def count_prompt_tokens(msgs: list[dict[str, str]]) -> int:
    cfg = _S()
    overhead = int(cfg.get("prompt_per_message_overhead", 4))
    return sum(approx_tokens(m.get("content", "")) + overhead for m in msgs)


def get_session(session_id: str):
    cfg = _S()
    recent_maxlen = int(cfg.get("recent_maxlen", 50))
    st = SESSIONS.setdefault(
        session_id,
        {
            "summary": "",
            "recent": deque(maxlen=recent_maxlen),
            "style": get_style_sys(),
            "short": False,
            "bullets": False,
        },
    )
    if not st["summary"]:
        try:
            st["summary"] = store_get_summary(session_id) or ""
        except Exception:
            pass
    if not st["recent"]:
        try:
            rows = store_list_messages(session_id)
            tail = rows[-st["recent"].maxlen :]
            for m in tail:
                st["recent"].append({"role": m.role, "content": strip_runjson(m.content)})
        except Exception:
            pass
    return st


def _heuristic_bullets(chunks: list[dict[str, str]], cfg: dict) -> str:
    max_bullets = int(cfg.get("heuristic_max_bullets", 8))
    max_words = int(cfg.get("heuristic_max_words", 40))
    prefix = cfg.get("bullet_prefix", "• ")

    bullets: list[str] = []
    for m in chunks:
        txt = " ".join((m.get("content") or "").split())
        if not txt:
            continue
        words = txt.replace("\n", " ").split()
        snippet = " ".join(words[:max_words]) if words else ""
        bullets.append(f"{prefix}{snippet}" if snippet else prefix.strip())
        if len(bullets) >= max_bullets:
            break
    return "\n".join(bullets) if bullets else prefix.strip()


def summarize_chunks(chunks: list[dict[str, str]]) -> tuple[str, bool]:
    cfg = _S()
    t0 = time.time()
    PACK_TELEMETRY["summarySec"] = 0.0
    PACK_TELEMETRY["summaryTokensApprox"] = 0
    PACK_TELEMETRY["summaryUsedLLM"] = False
    PACK_TELEMETRY["summaryBullets"] = 0
    PACK_TELEMETRY["summaryAddedChars"] = 0
    PACK_TELEMETRY["summaryOutTokensApprox"] = 0

    if bool(cfg.get("use_fast_summary", True)):
        txt = _heuristic_bullets(chunks, cfg)
        dt = time.time() - t0
        PACK_TELEMETRY["summarySec"] = float(dt)
        PACK_TELEMETRY["summaryTokensApprox"] = int(approx_tokens(txt))
        PACK_TELEMETRY["summaryUsedLLM"] = False
        PACK_TELEMETRY["summaryBullets"] = len([l for l in txt.splitlines() if l.strip()])
        PACK_TELEMETRY["summaryAddedChars"] = len(txt)
        PACK_TELEMETRY["summaryOutTokensApprox"] = int(approx_tokens(txt))
        return txt, False

    # LLM summary path
    text = "\n".join(f"{m.get('role', '')}: {m.get('content', '')}" for m in chunks)
    sys_inst = cfg.get("summary_sys_inst", "")
    user_prefix = cfg.get("summary_user_prefix", "")
    user_suffix = cfg.get("summary_user_suffix", "")
    user_prompt = user_prefix + text + user_suffix

    llm = get_llm()
    out = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": sys_inst},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=int(cfg.get("llm_summary_max_tokens", 256)),
        temperature=float(cfg.get("llm_summary_temperature", 0.2)),
        top_p=float(cfg.get("llm_summary_top_p", 1.0)),
        stream=False,
        stop=list(cfg.get("llm_summary_stop", [])),
    )
    raw = (out["choices"][0]["message"]["content"] or "").strip()
    lines = [ln.strip() for ln in raw.splitlines()]
    bullets: list[str] = []
    seen = set()
    max_words = int(cfg.get("heuristic_max_words", 40))
    max_bullets = int(cfg.get("heuristic_max_bullets", 8))
    bullet_prefix = cfg.get("bullet_prefix", "• ")

    for ln in lines:
        if not ln.startswith(bullet_prefix):
            continue
        norm = " ".join(ln[len(bullet_prefix) :].lower().split())
        if not norm or norm in seen:
            continue
        seen.add(norm)
        words = ln[len(bullet_prefix) :].split()
        if len(words) > max_words:
            ln = bullet_prefix + " ".join(words[:max_words])
        bullets.append(ln)
        if len(bullets) >= max_bullets:
            break

    if bullets:
        txt = "\n".join(bullets)
        dt = time.time() - t0
        PACK_TELEMETRY["summarySec"] = float(dt)
        PACK_TELEMETRY["summaryTokensApprox"] = int(
            approx_tokens(sys_inst) + approx_tokens(user_prompt) + approx_tokens(txt)
        )
        PACK_TELEMETRY["summaryUsedLLM"] = True
        PACK_TELEMETRY["summaryBullets"] = len(bullets)
        PACK_TELEMETRY["summaryAddedChars"] = len(txt)
        PACK_TELEMETRY["summaryOutTokensApprox"] = int(approx_tokens(txt))
        return txt, True

    # Fallback: single bullet
    s = " ".join(raw.split())[:160]
    fallback = (bullet_prefix + s) if s else bullet_prefix.strip()
    dt = time.time() - t0
    PACK_TELEMETRY["summarySec"] = float(dt)
    PACK_TELEMETRY["summaryTokensApprox"] = int(
        approx_tokens(sys_inst) + approx_tokens(user_prompt) + approx_tokens(fallback)
    )
    PACK_TELEMETRY["summaryUsedLLM"] = True
    PACK_TELEMETRY["summaryBullets"] = len([l for l in fallback.splitlines() if l.strip()])
    PACK_TELEMETRY["summaryAddedChars"] = len(fallback)
    PACK_TELEMETRY["summaryOutTokensApprox"] = int(approx_tokens(fallback))
    return fallback, True


def _compress_summary_block(s: str) -> str:
    cfg = _S()
    max_chars = int(cfg.get("summary_max_chars", 1200))
    prefix = cfg.get("bullet_prefix", "• ")
    lines = [ln.strip() for ln in (s or "").splitlines()]

    out, seen = [], set()
    for ln in lines:
        if not ln.startswith(prefix):
            continue
        norm = " ".join(ln[len(prefix) :].lower().split())
        if norm in seen:
            continue
        seen.add(norm)
        out.append(ln)

    text = "\n".join(out)
    PACK_TELEMETRY["summaryCompressedFromChars"] = len(s or "")

    if len(text) > max_chars:
        last, total = [], 0
        for ln in reversed(out):
            if total + len(ln) + 1 > max_chars:
                break
            last.append(ln)
            total += len(ln) + 1
        text = "\n".join(reversed(last))

    PACK_TELEMETRY["summaryCompressedToChars"] = len(text)
    PACK_TELEMETRY["summaryCompressedDroppedChars"] = int(
        max(
            0,
            int(PACK_TELEMETRY["summaryCompressedFromChars"])
            - int(PACK_TELEMETRY["summaryCompressedToChars"]),
        )
    )
    return text
