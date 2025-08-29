from __future__ import annotations
from typing import Tuple, Optional, Any
import json, re, traceback
from ..core.settings import SETTINGS

# --------- Prompt (brace-safe; only {text} is formatted) ----------
_DECIDE_PROMPT = (
    "You are a router deciding whether the user message should query the app's LOCAL knowledge "
    "(uploaded files, chat/session documents) via RAG.\n"
    "Respond with JSON only in exactly this schema:\n"
    "{{\"need\": true|false, \"query\": \"<text or empty>\"}}\n\n"
    "Decision principle:\n"
    "- Set need=true if answering would materially benefit from the user's LOCAL knowledge base "
    "(e.g., their files, prior session uploads, or internal notes).\n"
    "- Set need=false if the answer is general knowledge or can be answered without consulting local files.\n"
    "- Do NOT consider the public web here.\n"
    "- If you set need=true and you can succinctly restate the search intent for the local KB, "
    "  put that in \"query\". Otherwise leave \"query\" empty.\n\n"
    "Text:\n{text}\n"
    "JSON:"
)

def _dbg(msg: str):
    print(f"[RAG ROUTER] {msg}")

def _force_json(s: str) -> dict:
    if not s:
        _dbg("empty LLM output")
        return {}
    # try direct
    try:
        v = json.loads(s)
        if isinstance(v, dict):
            _dbg(f"JSON direct OK keys={list(v.keys())}")
            return v
        _dbg(f"JSON direct produced non-dict type={type(v).__name__}")
    except Exception as e:
        _dbg(f"direct loads failed: {e} | text={s!r}")

    # settings regex
    rgx = SETTINGS.get("router_json_extract_regex")
    cand = None
    if isinstance(rgx, str) and rgx:
        try:
            m = re.search(rgx, s, re.DOTALL)
            if m:
                cand = m.group(0)
                _dbg(f"regex cand via settings len={len(cand)}")
        except Exception as e:
            _dbg(f"settings regex error: {e}")

    # fallback: first {...}
    if not cand:
        m2 = re.search(r"\{.*?\}", s, re.DOTALL)
        cand = m2.group(0) if m2 else None
        if cand:
            _dbg(f"fallback cand len={len(cand)}")

    if not cand:
        _dbg("no JSON candidate found")
        return {}

    try:
        v = json.loads(cand)
        if isinstance(v, dict):
            _dbg(f"cand loads OK keys={list(v.keys())}")
            return v
        _dbg(f"cand loads non-dict type={type(v).__name__}")
    except Exception as e:
        _dbg(f"cand loads failed: {e} | cand={cand!r}")
    return {}

def _strip_wrappers(text: str) -> str:
    t = (text or "")
    if SETTINGS.get("router_trim_whitespace") is True:
        t = t.strip()
    if SETTINGS.get("router_strip_wrappers_enabled") is not True:
        return t
    head = t
    if SETTINGS.get("router_strip_split_on_blank") is True:
        head = t.split("\n\n", 1)[0]
    pat = SETTINGS.get("router_strip_header_regex")
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
        except Exception as e:
            _dbg(f"strip_wrappers regex error: {e}")
            return head
    return head

def _normalize_keys(d: dict) -> dict:
    """Make keys robust: strip quotes/spaces and lowercase."""
    norm = {}
    for k, v in d.items():
        ks = str(k).strip().strip('"').strip("'").strip().lower()
        norm[ks] = v
    return norm

def _as_bool(v) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().strip('"').strip("'").lower()
        if s in ("true", "yes", "y", "1"):
            return True
        if s in ("false", "no", "n", "0"):
            return False
    return None

def decide_rag(llm: Any, user_text: str) -> Tuple[bool, Optional[str]]:
    try:
        if not user_text or not user_text.strip():
            _dbg("SKIP empty user_text")
            return (False, None)

        core_text = _strip_wrappers(user_text.strip())
        the_prompt = _DECIDE_PROMPT.format(text=core_text)
        _dbg(f"INPUT core_text={core_text!r}")
        _dbg(f"PROMPT >>>\n{the_prompt}\n<<< PROMPT")

        params = {
            "max_tokens": SETTINGS.get("router_decide_max_tokens"),
            "temperature": SETTINGS.get("router_decide_temperature"),
            "top_p": SETTINGS.get("router_decide_top_p"),
            "stream": False,
        }
        stop_list = SETTINGS.get("router_decide_stop")
        if isinstance(stop_list, list) and stop_list:
            params["stop"] = stop_list
        params = {k: v for k, v in params.items() if v is not None}
        _dbg(f"PARAMS={params}")

        raw = llm.create_chat_completion(
            messages=[{"role": "user", "content": the_prompt}],
            **params,
        )
        _dbg(f"RAW OBJ keys={list(raw.keys())}")
        text_out = (raw.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        _dbg(f"RAW OUT str={text_out!r}")

        data = _force_json(text_out) or {}
        _dbg(f"PARSED JSON raw={data}")

        data = _normalize_keys(data)
        _dbg(f"PARSED JSON norm_keys={data}")

        need_raw = data.get("need")
        need_bool = _as_bool(need_raw) if not isinstance(need_raw, bool) else need_raw
        if need_bool is None:
            need_default = SETTINGS.get("rag_default_need_when_invalid")
            need = bool(need_default) if isinstance(need_default, bool) else False
            _dbg(f"'need' missing/invalid -> default={need}")
        else:
            need = bool(need_bool)

        query_field = data.get("query", "")
        try:
            query = _strip_wrappers(str(query_field or "").strip())
        except Exception as e:
            _dbg(f"query strip error: {e}")
            query = ""

        if not need:
            query = None
        _dbg(f"DECISION need={need} query={query!r}")
        return (need, query)

    except Exception as e:
        _dbg(f"FATAL {type(e).__name__}: {e}")
        traceback.print_exc()
        return (bool(SETTINGS.get("rag_default_need_when_invalid", False)), None)
