# ===== aimodel/file_read/rag/router_ai.py =====
from __future__ import annotations
from typing import Tuple, Optional, Any
import json, re, traceback
from ..core.settings import SETTINGS

def _dbg(msg: str):
    print(f"[RAG ROUTER] {msg}")

def _force_json_strict(s: str) -> dict:
    if not s:
        return {}
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {}
    except Exception:
        pass
    rgx = SETTINGS.get("router_rag_json_extract_regex")
    if isinstance(rgx, str) and rgx:
        try:
            m = re.search(rgx, s, re.DOTALL)
            if m:
                cand = m.group(0)
                v = json.loads(cand)
                return v if isinstance(v, dict) else {}
        except Exception:
            pass
    return {}

def _strip_wrappers(text: str) -> str:
    t = text or ""
    if SETTINGS.get("router_rag_trim_whitespace") is True:
        t = t.strip()
    if SETTINGS.get("router_rag_strip_wrappers_enabled") is not True:
        return t
    head = t
    if SETTINGS.get("router_rag_strip_split_on_blank") is True:
        head = t.split("\n\n", 1)[0]
    pat = SETTINGS.get("router_rag_strip_header_regex")
    if isinstance(pat, str) and pat:
        try:
            rx = re.compile(pat)
            out = []
            for ln in head.splitlines():
                if rx.match(ln):
                    break
                out.append(ln)
            core = " ".join(" ".join(out).split())
            return core if core else t
        except Exception:
            return head
    return head

def _normalize_keys(d: dict) -> dict:
    return {str(k).strip().strip('"').strip("'").strip().lower(): v for k, v in d.items()}

def _as_bool(v) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().strip('"').strip("'").lower()
        if s in ("true", "yes", "y", "1"):  return True
        if s in ("false", "no", "n", "0"):  return False
    return None

def decide_rag(llm: Any, user_text: str) -> Tuple[bool, Optional[str]]:
    try:
        if not user_text or not user_text.strip():
            return (False, None)

        core_text = _strip_wrappers(user_text.strip())

        prompt_tpl = SETTINGS.get("router_rag_decide_prompt")
        if not isinstance(prompt_tpl, str) or ("$text" not in prompt_tpl and "{text}" not in prompt_tpl):
            _dbg("router_rag_decide_prompt missing/invalid")
            return (False, None)

        from string import Template
        if "$text" in prompt_tpl:
            the_prompt = Template(prompt_tpl).safe_substitute(text=core_text)
        else:
            the_prompt = prompt_tpl.format(text=core_text)

        params = {
            "max_tokens": SETTINGS.get("router_rag_decide_max_tokens"),
            "temperature": SETTINGS.get("router_rag_decide_temperature"),
            "top_p": SETTINGS.get("router_rag_decide_top_p"),
            "stream": False,
        }
        stop_list = SETTINGS.get("router_rag_decide_stop")
        if isinstance(stop_list, list) and stop_list:
            params["stop"] = stop_list
        params = {k: v for k, v in params.items() if v is not None}

        raw = llm.create_chat_completion(
            messages=[{"role": "user", "content": the_prompt}],
            **params,
        )
        text_out = (raw.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()

        data = _force_json_strict(text_out)
        if not isinstance(data, dict):
            need_default = SETTINGS.get("router_rag_default_need_when_invalid")
            return (bool(need_default) if isinstance(need_default, bool) else False, None)
        data = _normalize_keys(data)

        need_raw = data.get("need")
        need_bool = _as_bool(need_raw) if not isinstance(need_raw, bool) else need_raw
        if need_bool is None:
            need_default = SETTINGS.get("router_rag_default_need_when_invalid")
            return (bool(need_default) if isinstance(need_default, bool) else False, None)

        need = bool(need_bool)
        if not need:
            return (False, None)

        query_field = data.get("query", "")
        query_clean = _strip_wrappers(str(query_field or "").strip())
        if not query_clean:
            query_clean = core_text[:512]

        return (True, query_clean)

    except Exception as e:
        _dbg(f"FATAL {type(e).__name__}: {e}")
        traceback.print_exc()
        need_default = SETTINGS.get("router_rag_default_need_when_invalid")
        return (bool(need_default) if isinstance(need_default, bool) else False, None)
