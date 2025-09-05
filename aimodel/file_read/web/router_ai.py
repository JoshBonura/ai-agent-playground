from __future__ import annotations
from typing import Tuple, Optional, Any, Dict
import json, re, time
from ..core.settings import SETTINGS
from ..utils.streaming import safe_token_count_messages

def _force_json(s: str) -> dict:
    if not s:
        return {}
    raw = s.strip()
    try:
        cf = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
        if cf:
            raw = cf.group(1).strip()
    except Exception:
        pass
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except Exception:
        pass
    try:
        m = None
        for m in re.finditer(r"\{[^{}]*\"need\"\s*:\s*(?:true|false|\"true\"|\"false\")[^{}]*\}", raw, re.IGNORECASE):
            pass
        if m:
            frag = m.group(0)
            v = json.loads(frag)
            return v if isinstance(v, dict) else {}
    except Exception:
        pass
    try:
        last = None
        for last in re.finditer(r"\{[\s\S]*\}", raw):
            pass
        if last:
            frag = last.group(0)
            v = json.loads(frag)
            return v if isinstance(v, dict) else {}
    except Exception:
        pass
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
        except Exception:
            return head
    return head

def decide_web(llm: Any, user_text: str) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    telemetry: Dict[str, Any] = {}
    try:
        if not user_text or not user_text.strip():
            return (False, None, telemetry)
        t_start = time.perf_counter()
        t_raw = user_text.strip()
        core_text = _strip_wrappers(t_raw)
        prompt_tpl = SETTINGS.get("router_decide_prompt")
        if not isinstance(prompt_tpl, str) or not prompt_tpl.strip():
            return (False, None, telemetry)
        the_prompt = _safe_prompt_format(prompt_tpl, text=core_text)
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
        telemetry["rawRouterOut"] = text_out[:2000]
        data = _force_json(text_out) or {}
        need_val = data.get("need", None)
        if isinstance(need_val, str):
            nv = need_val.strip().lower()
            if nv in ("true", "yes", "y", "1"):
                need_val = True
            elif nv in ("false", "no", "n", "0"):
                need_val = False
        if isinstance(need_val, bool):
            need = need_val
            parsed_ok = True
        else:
            parsed_ok = False
            need_default = SETTINGS.get("router_default_need_when_invalid")
            need = bool(need_default) if isinstance(need_default, bool) else False
        query_field = data.get("query", "")
        try:
            query = _strip_wrappers(str(query_field or "").strip())
        except Exception:
            query = ""
        if not need:
            query = None
        t_elapsed = time.perf_counter() - t_start
        in_tokens = safe_token_count_messages(llm, [{"role": "user", "content": the_prompt}]) or 0
        out_tokens = safe_token_count_messages(llm, [{"role": "assistant", "content": text_out}]) or 0
        telemetry.update({
            "needed": bool(need),
            "routerQuery": query if need else None,
            "elapsedSec": round(t_elapsed, 4),
            "inputTokens": in_tokens,
            "outputTokens": out_tokens,
            "parsedOk": parsed_ok,
        })
        return (need, query, telemetry)
    except Exception:
        return (False, None, telemetry)

async def decide_web_and_fetch(llm: Any, user_text: str, *, k: int = 3) -> Tuple[Optional[str], Dict[str, Any]]:
    telemetry: Dict[str, Any] = {}
    need, proposed_q, tel_decide = decide_web(llm, (user_text or "").strip())
    telemetry.update(tel_decide)
    if not need:
        return None, telemetry
    from .query_summarizer import summarize_query
    from .orchestrator import build_web_block
    base_query = _strip_wrappers((proposed_q or user_text).strip())
    try:
        q_summary, tel_sum = summarize_query(llm, base_query)
        q_summary = _strip_wrappers((q_summary or "").strip()) or base_query
        telemetry["summarizer"] = tel_sum
        telemetry["summarizedQuery"] = q_summary
    except Exception:
        q_summary = base_query
    t_start = time.perf_counter()
    try:
        block_res = await build_web_block(q_summary, k=k)
        if isinstance(block_res, tuple):
            block, tel_orch = block_res
            telemetry["orchestrator"] = tel_orch or {}
        else:
            block = block_res
    except Exception:
        block = None
    t_elapsed = time.perf_counter() - t_start
    telemetry.update({
        "fetchElapsedSec": round(t_elapsed, 4),
        "blockChars": len(block) if block else 0,
    })
    return (block or None, telemetry)

def _safe_prompt_format(tpl: str, **kwargs) -> str:
    marker = "__ROUTER_TEXT_FIELD__"
    tmp = tpl.replace("{text}", marker)
    tmp = tmp.replace("{", "{{").replace("}", "}}")
    tmp = tmp.replace(marker, "{text}")
    return tmp.format(**kwargs)
