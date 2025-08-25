# aimodel/file_read/web/router_ai.py
from __future__ import annotations
from typing import Tuple, Optional, Any
import json, re
from ..core.settings import SETTINGS

# ---- Hardcoded, brace-safe prompt (only {text} is formatted) -----------------
_DECIDE_PROMPT = (
    "You are a router deciding whether answering the text requires the public web.\n"
    "Respond with JSON only in exactly this schema:\n"
    "{{\"need\": true|false, \"query\": \"<text or empty>\"}}\n\n"
    "Decision principle:\n"
    "- The answer requires the web if any part of it depends on information that is not contained in the user text and is not static/stable over time.\n"
    "- Capability boundary: Assume you have no access to real-time state (including the current system date/time, clocks, live data feeds) or hidden tools beyond this routing step.\n"
    "- If the correct answer depends on real-time state (e.g., ‘current’ values, now/today/tomorrow semantics, live figures, roles that may change, schedules, prices, weather, scores, news), set need=true.\n"
    "- If the answer can be derived entirely from the user text plus stable knowledge, set need=false.\n"
    "- When uncertain whether real-time state is required, prefer need=true.\n\n"
    "Text:\n{text}\n"
    "JSON:"
)

# ---- JSON extraction (configurable) -----------------------------------------
def _force_json(s: str) -> dict:
    if not s:
        return {}
    # Primary: straight JSON
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {}
    except Exception:
        pass

    # Settings-provided regex (recommended: non-greedy first-block)
    rgx = SETTINGS.get("router_json_extract_regex")
    cand = None
    if isinstance(rgx, str) and rgx:
        try:
            m = re.search(rgx, s, re.DOTALL)
            if m:
                cand = m.group(0)
        except Exception:
            cand = None

    # Fallback: first non-greedy {...}
    if not cand:
        m2 = re.search(r"\{.*?\}", s, re.DOTALL)
        cand = m2.group(0) if m2 else None

    if not cand:
        return {}
    try:
        v = json.loads(cand)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}

# ---- Strip wrappers (configurable) ------------------------------------------
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
        except Exception:
            return head
    return head

# ---- Core router -------------------------------------------------------------
def decide_web(llm: Any, user_text: str) -> Tuple[bool, Optional[str]]:
    try:
        if not user_text or not user_text.strip():
            print("[ROUTER] SKIP (empty user_text)")
            return (False, None)

        t_raw = user_text.strip()
        core_text = _strip_wrappers(t_raw)
        print(f"[ROUTER] INPUT raw={t_raw!r} core={core_text!r}")

        # Explicit overrides (prefixes configurable)
        prefixes = SETTINGS.get("router_explicit_prefixes")
        if isinstance(prefixes, list) and prefixes:
            low = t_raw.lower()
            for p in prefixes:
                ps = str(p or "").lower()
                if ps and low.startswith(ps):
                    q = t_raw.split(":", 1)[1].strip() if ":" in t_raw else t_raw
                    q = _strip_wrappers(q)
                    print(f"[ROUTER] EXPLICIT override need_web=True query={q!r}")
                    return (True, q)

        # Hardcoded prompt; all other knobs from settings
        the_prompt = _DECIDE_PROMPT.format(text=core_text)
        print(f"[ROUTER] PROMPT >>>\n{the_prompt}\n<<< PROMPT")

        # Build generation params from settings (filter out None)
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

        raw_out_obj = llm.create_chat_completion(
            messages=[{"role": "user", "content": the_prompt}],
            **params,
        )
        text_out = (raw_out_obj.get("choices", [{}])[0]
                                  .get("message", {})
                                  .get("content") or "").strip()

        try:
            print(f"[ROUTER] RAW OBJ keys={list(raw_out_obj.keys())}")
        except Exception:
            pass
        print(f"[ROUTER] RAW OUT str={text_out!r}")

        data = _force_json(text_out) or {}
        print(f"[ROUTER] PARSED JSON={data}")

        # Keep it strict: bool only; otherwise fallback to default
        need_val = data.get("need", None)
        if isinstance(need_val, bool):
            need = need_val
        else:
            need_default = SETTINGS.get("router_default_need_when_invalid")
            need = bool(need_default) if isinstance(need_default, bool) else False

        query_field = data.get("query", "")
        try:
            query = _strip_wrappers(str(query_field or "").strip())
        except Exception:
            query = ""

        if not need:
            query = None

        print(f"[ROUTER] DECISION need_web={need} query={query!r}")
        return (need, query)

    except Exception as e:
        print(f"[ROUTER] FATAL in decide_web: {type(e).__name__}: {e}")
        return (False, None)

# ---- One-hop decide + fetch --------------------------------------------------
async def decide_web_and_fetch(llm: Any, user_text: str, *, k: int = 3) -> Optional[str]:
    t = (user_text or "").strip()
    prev = (t[:160] + "…") if len(t) > 160 else t
    print(f"[ROUTER:FETCH] IN text_len={len(t)} k={k} text_preview={prev!r}")

    need, proposed_q = decide_web(llm, t)
    print(f"[ROUTER:FETCH] decide_web -> need={need} proposed_q={proposed_q!r}")
    if not need:
        print("[ROUTER:FETCH] no web needed")
        return None

    # Lazy imports to avoid circulars
    from .query_summarizer import summarize_query
    from .orchestrator import build_web_block

    base_query = _strip_wrappers((proposed_q or t).strip())
    try:
        q_summary = (summarize_query(llm, base_query) or "").strip().strip('"\'' ) or base_query
        q_summary = _strip_wrappers(q_summary)
        print(f"[ROUTER:FETCH] summarize_query base={base_query!r} -> q_summary={q_summary!r}")
    except Exception as e:
        print(f"[ROUTER:FETCH] summarize_query ERROR {type(e).__name__}: {e}")
        q_summary = base_query

    try:
        block = await build_web_block(q_summary, k=k)
        print(f"[ROUTER:FETCH] build_web_block len={(len(block) if block else 0)}")
    except Exception as e:
        print(f"[ROUTER:FETCH] build_web_block ERROR {type(e).__name__}: {e}")
        block = None

    return block or None
