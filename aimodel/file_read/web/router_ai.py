# aimodel/file_read/web/router_ai.py
from __future__ import annotations
from typing import Tuple, Optional, Any
import json, re

# ---- Minimal JSON-only prompt (model decides; no heuristics) -----------------
# IMPORTANT: All braces are doubled {{ }} so .format(text=...) doesn't try to
# substitute keys like "need" and "query".
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
# ---- Robust JSON extraction (no content heuristics) --------------------------
def _force_json(s: str) -> dict:
    if not s:
        return {}
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {}
    except Exception:
        m = re.search(r"\{.*\}", s or "", re.DOTALL)
        if not m:
            return {}
        try:
            v = json.loads(m.group(0))
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}

# ---- Strip wrappers (Context:, Summary:) for cleaner routing -----------------
def _strip_wrappers(text: str) -> str:
    """
    Keep only the leading user question. Cut at first blank line and stop
    when a line looks like a section header (.*:). Formatting cleanup only.
    """
    t = (text or "").strip()
    head = t.split("\n\n", 1)[0]
    out = []
    for ln in head.splitlines():
        if re.match(r"^\s*\w[^:\n]{0,40}:\s*$", ln):
            break
        out.append(ln)
    core = " ".join(" ".join(out).split())
    return core or t

# ---- Core router -------------------------------------------------------------
def decide_web(llm: Any, user_text: str) -> Tuple[bool, Optional[str]]:
    try:
        if not user_text or not user_text.strip():
            print("[ROUTER] SKIP (empty user_text)")
            return (False, None)

        t_raw = user_text.strip()
        core_text = _strip_wrappers(t_raw)

        print(f"[ROUTER] INPUT raw={t_raw!r} core={core_text!r}")

        # Explicit override (user forces web)
        low = t_raw.lower()
        if low.startswith("web:") or low.startswith("search:"):
            q = t_raw.split(":", 1)[1].strip() or t_raw
            q = _strip_wrappers(q)
            print(f"[ROUTER] EXPLICIT override need_web=True query={q!r}")
            return (True, q)

        # Model-based decision (no heuristics). Prefer no web if undecided.
        prompt = _DECIDE_PROMPT.format(text=core_text)
        print(f"[ROUTER] PROMPT >>>\n{prompt}\n<<< PROMPT")

        text_out = ""
        raw_out_obj = None
        try:
            raw_out_obj = llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=96,
                temperature=0.0,
                top_p=1.0,
                stream=False,
                # Avoid stopping on '\n\n' which can truncate JSON.
                stop=["</s>"],
            )
            text_out = (raw_out_obj.get("choices", [{}])[0]
                                      .get("message", {})
                                      .get("content") or "").strip()
        except Exception as e:
            print(f"[ROUTER] primary call error: {type(e).__name__}: {e}")
            # Fallback retry without stop tokens (some wrappers are picky)
            try:
                raw_out_obj = llm.create_chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=96,
                    temperature=0.0,
                    top_p=1.0,
                    stream=False,
                )
                text_out = (raw_out_obj.get("choices", [{}])[0]
                                          .get("message", {})
                                          .get("content") or "").strip()
            except Exception as e2:
                print(f"[ROUTER] fallback call error: {type(e2).__name__}: {e2}")
                text_out = ""

        try:
            if isinstance(raw_out_obj, dict):
                print(f"[ROUTER] RAW OBJ keys={list(raw_out_obj.keys())}")
            else:
                print(f"[ROUTER] RAW OBJ type={type(raw_out_obj)}")
        except Exception:
            pass
        print(f"[ROUTER] RAW OUT str={text_out!r}")

        data = _force_json(text_out) or {}
        print(f"[ROUTER] PARSED JSON={data}")

        need_val = data.get("need", None)
        need = bool(need_val) if isinstance(need_val, bool) else False

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
