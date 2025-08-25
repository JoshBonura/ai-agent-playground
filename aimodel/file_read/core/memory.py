from __future__ import annotations
import math, time, json
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

def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def _log(msg: str) -> None:
    print(f"[{_now()}] {msg}")

def _snapshot(cfg: Dict) -> str:
    """Short human-readable snapshot of the most important knobs."""
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
        self.path: Path = EFFECTIVE_SETTINGS_FILE  # central path
        self._mtime: float | None = None
        self._data: Dict = {}
        _log(f"settings path = {self.path}")

    def get(self) -> Dict:
        """Load EFFECTIVE settings (defaults ⟶ adaptive ⟶ overrides)."""
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
    use_fast = bool(cfg["use_fast_summary"])
    _log(f"summarize_chunks IN chunks={len(chunks)} FAST={use_fast}")
    if use_fast:
        txt = _heuristic_bullets(chunks, cfg)
        dt = time.time() - t0
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
        _log(f"summarize_chunks OUT bullets={len(bullets)} chars={len(txt)} dt={dt:.2f}s")
        return txt, True
    s = " ".join(raw.split())[:160]
    fallback = (cfg["bullet_prefix"] + s) if s else cfg["bullet_prefix"].strip()
    dt = time.time() - t0
    _log(f"summarize_chunks OUT bullets=0 chars={len(fallback)} dt={dt:.2f}s (FALLBACK)")
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
    _log(f"compress_summary IN chars={len(s)} kept_lines={len(out)}")
    if len(text) > max_chars:
        last, total = [], 0
        for ln in reversed(out):
            if total + len(ln) + 1 > max_chars:
                break
            last.append(ln)
            total += len(ln) + 1
        text = "\n".join(reversed(last))
    _log(f"compress_summary OUT chars={len(text)} lines={len(text.splitlines())}")
    return text

def build_system(style: str, short: bool, bullets: bool) -> str:
    cfg = _SETTINGS.get()
    _log(f"build_system flags short={short} bullets={bullets}")
    parts = [STYLE_SYS]
    if style and style != STYLE_SYS:
        parts.append(style)
    if short:
        parts.append(cfg["system_brief_directive"])
    if bullets:
        parts.append(cfg["system_bullets_directive"])
    parts.append(cfg["system_follow_user_style_directive"])
    return " ".join(parts)

def pack_messages(style: str, short: bool, bullets: bool, summary, recent, max_ctx, out_budget):
    cfg = _SETTINGS.get()
    model_ctx = int(max_ctx or cfg["model_ctx"])
    gen_budget = int(out_budget or cfg["out_budget"])
    reserved = int(cfg["reserved_system_tokens"])
    input_budget = model_ctx - gen_budget - reserved
    if input_budget < int(cfg["min_input_budget"]):
        input_budget = int(cfg["min_input_budget"])
    sys_text = build_system(style, short, bullets)
    prologue = [{"role": "user", "content": sys_text}]
    if summary:
        prologue.append({"role": "user", "content": cfg["summary_header_prefix"] + summary})
    packed = prologue + list(recent)
    _log(f"pack_messages SETTINGS snapshot: {_snapshot(cfg)}")
    _log(f"pack_messages OUT msgs={len(packed)} tokens~{count_prompt_tokens(packed)} "
         f"(model_ctx={model_ctx}, out_budget={gen_budget}, input_budget={input_budget})")
    return packed, input_budget

def _final_safety_trim(packed: List[Dict[str,str]], input_budget: int) -> List[Dict[str,str]]:
    cfg = _SETTINGS.get()
    keep_ratio = float(cfg["final_shrink_summary_keep_ratio"])
    min_keep = int(cfg["final_shrink_summary_min_chars"])
    def toks() -> int:
        try:
            return count_prompt_tokens(packed)
        except Exception:
            return 999999
    _log(f"final_trim START tokens={toks()} budget={input_budget}")
    keep_head = 2 if len(packed) >= 2 and isinstance(packed[1].get("content"), str) and packed[1]["content"].startswith(cfg["summary_header_prefix"]) else 1
    while toks() > input_budget and len(packed) > keep_head + 1:
        dropped = packed.pop(keep_head)
        _log(f"final_trim DROP msg role={dropped['role']} size~{approx_tokens(dropped['content'])} toks={toks()}")
    if toks() > input_budget and keep_head == 2 and len(packed) >= 2:
        summary_msg = packed[1]
        txt = summary_msg["content"]
        n = max(min_keep, int(len(txt) * keep_ratio))
        summary_msg["content"] = txt[-n:]
        _log(f"final_trim SHRINK summary to {len(summary_msg['content'])} chars toks={toks()}")
    if toks() > input_budget and keep_head == 2 and len(packed) >= 2:
        removed = packed.pop(1)
        _log(f"final_trim REMOVE summary len~{len(removed['content'])} toks={toks()}")
    while toks() > input_budget and len(packed) > 2:
        removed = packed.pop(2 if len(packed) > 3 else 1)
        _log(f"final_trim LAST_RESORT drop size~{approx_tokens(removed['content'])} toks={toks()}")
    _log(f"final_trim END tokens={toks()} msgs={len(packed)}")
    return packed

def roll_summary_if_needed(packed, recent, summary, input_budget, system_text):
    cfg = _SETTINGS.get()

    # --- DEBUG SNAPSHOT ---
    _log("=== roll_summary_if_needed DEBUG START ===")
    _log(f"skip_overage_lt={cfg['skip_overage_lt']}, "
         f"max_peel_per_turn={cfg['max_peel_per_turn']}, "
         f"peel_min={cfg['peel_min']}, "
         f"peel_frac={cfg['peel_frac']}, "
         f"peel_max={cfg['peel_max']}")
    _log(f"len(recent)={len(recent)}, current_summary_len={len(summary) if summary else 0}")
    _log(f"input_budget={input_budget}, reserved_system_tokens={cfg['reserved_system_tokens']}")
    _log(f"model_ctx={cfg['model_ctx']}, out_budget={cfg['out_budget']}")
    # ----------------------

    def _tok():
        try:
            return count_prompt_tokens(packed)
        except Exception:
            return 999999

    start_tokens = _tok()
    overage = start_tokens - input_budget
    _log(f"roll_summary_if_needed START tokens={start_tokens} "
         f"input_budget={input_budget} overage={overage}")

    if overage <= int(cfg["skip_overage_lt"]):
        _log(f"roll_summary_if_needed SKIP (overage {overage} <= {cfg['skip_overage_lt']})")
        packed = _final_safety_trim(packed, input_budget)
        return packed, summary

    peels_done = 0
    if len(recent) > 6 and peels_done < int(cfg["max_peel_per_turn"]):
        peel_min = int(cfg["peel_min"])
        peel_frac = float(cfg["peel_frac"])
        peel_max = int(cfg["peel_max"])
        target = max(peel_min, min(peel_max, int(len(recent) * peel_frac)))
        peel = []
        for _ in range(min(target, len(recent))):
            peel.append(recent.popleft())
        _log(f"roll_summary peeled={len(peel)}")
        new_sum, _used_llm = summarize_chunks(peel)
        if new_sum.startswith(cfg["bullet_prefix"]):
            summary = (summary + "\n" + new_sum).strip() if summary else new_sum
        else:
            summary = new_sum
        summary = _compress_summary_block(summary)
        packed = [
            {"role": "user", "content": system_text},
            {"role": "user", "content": cfg["summary_header_prefix"] + summary},
            *list(recent),
        ]
        _log(f"roll_summary updated summary_len={len(summary)} tokens={_tok()}")

    packed = _final_safety_trim(packed, input_budget)
    _log(f"roll_summary_if_needed END tokens={count_prompt_tokens(packed)}")
    _log("=== roll_summary_if_needed DEBUG END ===")
    return packed, summary