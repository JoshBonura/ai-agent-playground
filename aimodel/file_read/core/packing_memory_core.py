from __future__ import annotations
import math, time
from pathlib import Path
from typing import Dict, List, Tuple
from collections import deque

from ..runtime.model_runtime import get_llm
from .style import STYLE_SYS
from ..store import get_summary as store_get_summary
from ..store import list_messages as store_list_messages
from ..utils.streaming import strip_runjson
from ..core.files import EFFECTIVE_SETTINGS_FILE, load_json_file

SESSIONS: Dict[str, Dict] = {}
PACK_TELEMETRY: Dict[str, object] = {
    "packSec": 0.0,
    "summarySec": 0.0,
    "finalTrimSec": 0.0,
    "compressSec": 0.0,
    "summaryTokensApprox": 0,
    "summaryUsedLLM": False,
    "summaryBullets": 0,
    "summaryAddedChars": 0,
    "summaryOutTokensApprox": 0,
    "summaryCompressedFromChars": 0,
    "summaryCompressedToChars": 0,
    "summaryCompressedDroppedChars": 0,
}
SUMMARY_TEL = PACK_TELEMETRY

def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def _log(msg: str) -> None:
    print(f"[{_now()}] {msg}")

def _snapshot(cfg: Dict) -> str:
    keys = [
        "model_ctx", "out_budget", "reserved_system_tokens", "min_input_budget",
        "chars_per_token", "prompt_per_message_overhead",
        "summary_max_chars", "use_fast_summary",
    ]
    parts = []
    for k in keys:
        if k in cfg:
            parts.append(f"{k}={cfg[k]}")
    return ", ".join(parts)

class _SettingsCache:
    def __init__(self) -> None:
        self.path: Path = EFFECTIVE_SETTINGS_FILE
        self._mtime: float | None = None
        self._data: Dict = {}
        _log(f"settings path = {self.path}")

    def get(self) -> Dict:
        try:
            m = self.path.stat().st_mtime
        except FileNotFoundError:
            m = None
        if self._mtime != m or not self._data:
            self._data = load_json_file(self.path, default={})
            self._mtime = m
            _log(f"settings reload ok file={self.path.name} snapshot: {_snapshot(self._data)}")
        return self._data

_SETTINGS = _SettingsCache()

def approx_tokens(text: str) -> int:
    cfg = _SETTINGS.get()
    return max(1, math.ceil(len(text) / int(cfg["chars_per_token"])))

def count_prompt_tokens(msgs: List[Dict[str, str]]) -> int:
    cfg = _SETTINGS.get()
    overhead = int(cfg["prompt_per_message_overhead"])
    return sum(approx_tokens(m["content"]) + overhead for m in msgs)

def get_session(session_id: str):
    cfg = _SETTINGS.get()
    _log(f"get_session IN session={session_id} (settings: {_snapshot(cfg)})")
    st = SESSIONS.setdefault(session_id, {
        "summary": "",
        "recent": deque(maxlen=int(cfg["recent_maxlen"])),
        "style": STYLE_SYS,
        "short": False,
        "bullets": False,
    })
    if not st["summary"]:
        try:
            st["summary"] = store_get_summary(session_id) or ""
            _log(f"get_session loaded summary len={len(st['summary'])}")
        except Exception as e:
            _log(f"get_session summary load error {e}")
    if not st["recent"]:
        try:
            rows = store_list_messages(session_id)
            tail = rows[-st["recent"].maxlen:]
            for m in tail:
                st["recent"].append({"role": m.role, "content": strip_runjson(m.content)})
            _log(f"get_session hydrated recent={len(st['recent'])}")
        except Exception as e:
            _log(f"get_session hydrate error {e}")
    return st

def _heuristic_bullets(chunks: List[Dict[str,str]], cfg: Dict) -> str:
    max_bullets = int(cfg["heuristic_max_bullets"])
    max_words = int(cfg["heuristic_max_words"])
    prefix = cfg["bullet_prefix"]
    bullets = []
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

def summarize_chunks(chunks: List[Dict[str,str]]) -> Tuple[str, bool]:
    cfg = _SETTINGS.get()
    t0 = time.time()
    PACK_TELEMETRY["summarySec"] = 0.0
    PACK_TELEMETRY["summaryTokensApprox"] = 0
    PACK_TELEMETRY["summaryUsedLLM"] = False
    PACK_TELEMETRY["summaryBullets"] = 0
    PACK_TELEMETRY["summaryAddedChars"] = 0
    PACK_TELEMETRY["summaryOutTokensApprox"] = 0
    use_fast = bool(cfg["use_fast_summary"])
    _log(f"summarize_chunks IN chunks={len(chunks)} FAST={use_fast}")
    if use_fast:
        txt = _heuristic_bullets(chunks, cfg)
        dt = time.time() - t0
        PACK_TELEMETRY["summarySec"] = float(dt)
        PACK_TELEMETRY["summaryTokensApprox"] = int(approx_tokens(txt))
        PACK_TELEMETRY["summaryUsedLLM"] = False
        PACK_TELEMETRY["summaryBullets"] = len([l for l in txt.splitlines() if l.strip()])
        PACK_TELEMETRY["summaryAddedChars"] = len(txt)
        PACK_TELEMETRY["summaryOutTokensApprox"] = int(approx_tokens(txt))
        _log(f"summarize_chunks OUT (FAST) bullets={len([l for l in txt.splitlines() if l])} chars={len(txt)} dt={dt:.2f}s")
        return txt, False
    text = "\n".join(f'{m.get("role","")}: {m.get("content","")}' for m in chunks)
    sys_inst = cfg["summary_sys_inst"]
    user_prompt = cfg["summary_user_prefix"] + text + cfg["summary_user_suffix"]
    llm = get_llm()
    out = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": sys_inst},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=int(cfg["llm_summary_max_tokens"]),
        temperature=float(cfg["llm_summary_temperature"]),
        top_p=float(cfg["llm_summary_top_p"]),
        stream=False,
        stop=list(cfg["llm_summary_stop"]),
    )
    raw = (out["choices"][0]["message"]["content"] or "").strip()
    lines = [ln.strip() for ln in raw.splitlines()]
    bullets: List[str] = []
    seen = set()
    max_words = int(cfg["heuristic_max_words"])
    max_bullets = int(cfg["heuristic_max_bullets"])
    for ln in lines:
        if not ln.startswith(cfg["bullet_prefix"]):
            continue
        norm = " ".join(ln[len(cfg["bullet_prefix"]):].lower().split())
        if not norm or norm in seen:
            continue
        seen.add(norm)
        words = ln[len(cfg["bullet_prefix"]):].split()
        if len(words) > max_words:
            ln = cfg["bullet_prefix"] + " ".join(words[:max_words])
        bullets.append(ln)
        if len(bullets) >= max_bullets:
            break
    if bullets:
        txt = "\n".join(bullets)
        dt = time.time() - t0
        PACK_TELEMETRY["summarySec"] = float(dt)
        PACK_TELEMETRY["summaryTokensApprox"] = int(approx_tokens(sys_inst) + approx_tokens(user_prompt) + approx_tokens(txt))
        PACK_TELEMETRY["summaryUsedLLM"] = True
        PACK_TELEMETRY["summaryBullets"] = len(bullets)
        PACK_TELEMETRY["summaryAddedChars"] = len(txt)
        PACK_TELEMETRY["summaryOutTokensApprox"] = int(approx_tokens(txt))
        _log(f"summarize_chunks OUT bullets={len(bullets)} chars={len(txt)} dt={dt:.2f}s")
        return txt, True
    s = " ".join(raw.split())[:160]
    fallback = (cfg["bullet_prefix"] + s) if s else cfg["bullet_prefix"].strip()
    dt = time.time() - t0
    PACK_TELEMETRY["summarySec"] = float(dt)
    PACK_TELEMETRY["summaryTokensApprox"] = int(approx_tokens(sys_inst) + approx_tokens(user_prompt) + approx_tokens(fallback))
    PACK_TELEMETRY["summaryUsedLLM"] = True
    PACK_TELEMETRY["summaryBullets"] = len([l for l in fallback.splitlines() if l.strip()])
    PACK_TELEMETRY["summaryAddedChars"] = len(fallback)
    PACK_TELEMETRY["summaryOutTokensApprox"] = int(approx_tokens(fallback))
    _log(f"summarize_chunks OUT bullets=0 chars={len(fallback)} dt={dt:.2f}s")
    return fallback, True

def _compress_summary_block(s: str) -> str:
    cfg = _SETTINGS.get()
    max_chars = int(cfg["summary_max_chars"])
    prefix = cfg["bullet_prefix"]
    lines = [ln.strip() for ln in (s or "").splitlines()]
    out, seen = [], set()
    for ln in lines:
        if not ln.startswith(prefix):
            continue
        norm = " ".join(ln[len(prefix):].lower().split())
        if norm in seen:
            continue
        seen.add(norm)
        out.append(ln)
    text = "\n".join(out)
    PACK_TELEMETRY["summaryCompressedFromChars"] = int(len(s or ""))
    if len(text) > max_chars:
        last, total = [], 0
        for ln in reversed(out):
            if total + len(ln) + 1 > max_chars:
                break
            last.append(ln)
            total += len(ln) + 1
        text = "\n".join(reversed(last))
    PACK_TELEMETRY["summaryCompressedToChars"] = int(len(text))
    PACK_TELEMETRY["summaryCompressedDroppedChars"] = int(max(0, int(PACK_TELEMETRY["summaryCompressedFromChars"]) - int(PACK_TELEMETRY["summaryCompressedToChars"])))
    _log(f"compress_summary IN chars={len(s)} kept_lines={len(out)}")
    _log(f"compress_summary OUT chars={len(text)} lines={len(text.splitlines())}")
    return text
