from __future__ import annotations

import json
import re
import time
from typing import Any
import asyncio 
from ..core.logging import get_logger
from ..core.settings import SETTINGS
from ..utils.streaming import safe_token_count_messages
from ..utils.text import strip_wrappers as _strip_wrappers

log = get_logger(__name__)


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
        print("[_force_json] parsed whole raw")
        return v if isinstance(v, dict) else {}
    except Exception:
        pass
    try:
        m = None
        for m in re.finditer(
            r"\{[^{}]*\"need\"\s*:\s*(?:true|false|\"true\"|\"false\")[^{}]*\}", raw, re.IGNORECASE
        ):
            pass
        if m:
            frag = m.group(0)
            v = json.loads(frag)
            print("[_force_json] parsed frag with need field")
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
            print("[_force_json] parsed last {} block")
            return v if isinstance(v, dict) else {}
    except Exception:
        pass
    print("[_force_json] failed to parse JSON")
    return {}


def decide_web(llm: Any, user_text: str) -> tuple[bool, str | None, dict[str, Any]]:
    telemetry: dict[str, Any] = {}
    try:
        if not user_text or not user_text.strip():
            print("[decide_web] empty user_text")
            return (False, None, telemetry)
        t_start = time.perf_counter()
        t_raw = user_text.strip()
        if SETTINGS.get("router_strip_wrappers_enabled") is True:
            core_text = _strip_wrappers(
                t_raw,
                trim_whitespace=SETTINGS.get("router_trim_whitespace") is True,
                split_on_blank=SETTINGS.get("router_strip_split_on_blank") is True,
                header_regex=SETTINGS.get("router_strip_header_regex"),
            )
        else:
            core_text = t_raw.strip() if SETTINGS.get("router_trim_whitespace") is True else t_raw
        print(f"[decide_web] core_text={core_text[:100]!r}")
        prompt_tpl = SETTINGS.get("router_decide_prompt")
        if not isinstance(prompt_tpl, str) or not prompt_tpl.strip():
            print("[decide_web] no prompt template")
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
        print(f"[decide_web] sending prompt, params={params}")
        raw_out_obj = llm.create_chat_completion(
            messages=[{"role": "user", "content": the_prompt}],
            **params,
        )
        text_out = (
            raw_out_obj.get("choices", [{}])[0].get("message", {}).get("content") or ""
        ).strip()
        print(f"[decide_web] raw llm output={text_out[:200]!r}")
        telemetry["rawRouterOut"] = text_out[:2000]
        data = _force_json(text_out) or {}
        print(f"[decide_web] parsed data={data}")
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
            if SETTINGS.get("router_strip_wrappers_enabled") is True:
                query = _strip_wrappers(
                    str(query_field or "").strip(),
                    trim_whitespace=SETTINGS.get("router_trim_whitespace") is True,
                    split_on_blank=SETTINGS.get("router_strip_split_on_blank") is True,
                    header_regex=SETTINGS.get("router_strip_header_regex"),
                )
            else:
                query = str(query_field or "").strip()
        except Exception:
            query = ""
        if not need:
            query = None
        t_elapsed = time.perf_counter() - t_start
        in_tokens = safe_token_count_messages(llm, [{"role": "user", "content": the_prompt}]) or 0
        out_tokens = (
            safe_token_count_messages(llm, [{"role": "assistant", "content": text_out}]) or 0
        )
        telemetry.update(
            {
                "needed": bool(need),
                "routerQuery": query if need else None,
                "elapsedSec": round(t_elapsed, 4),
                "inputTokens": in_tokens,
                "outputTokens": out_tokens,
                "parsedOk": parsed_ok,
            }
        )
        print(f"[decide_web] result need={need}, query={query}")
        return (need, query, telemetry)
    except Exception as e:
        print(f"[decide_web] error: {e}")
        return (False, None, telemetry)


async def decide_web_and_fetch(
    llm: Any, user_text: str, *, k: int = 3, stop_ev: asyncio.Event | None = None
) -> tuple[str | None, dict[str, Any]]:
    telemetry: dict[str, Any] = {}
    need, proposed_q, tel_decide = decide_web(llm, (user_text or "").strip())
    telemetry.update(tel_decide)
    if not need:
        return None, telemetry

    # cancel before work
    if stop_ev is not None and stop_ev.is_set():
        telemetry["cancelled"] = True
        return None, telemetry

    from .orchestrator import build_web_block
    from .query_summarizer import summarize_query

    base_query = (proposed_q or user_text).strip()
    try:
        q_summary, tel_sum = summarize_query(llm, base_query)
        telemetry["summarizer"] = tel_sum
        q_summary = (q_summary or "").strip() or base_query
    except Exception:
        q_summary = base_query

    # cancel before fetch
    if stop_ev is not None and stop_ev.is_set():
        telemetry["cancelled"] = True
        return None, telemetry

    t_start = time.perf_counter()
    try:
        block, tel_orch = await build_web_block(q_summary, k=k, stop_ev=stop_ev)
        telemetry["orchestrator"] = tel_orch or {}
    except Exception:
        block = None
    telemetry.update(
        {
            "fetchElapsedSec": round(time.perf_counter() - t_start, 4),
            "blockChars": len(block) if block else 0,
        }
    )
    return (block or None, telemetry)



def _safe_prompt_format(tpl: str, **kwargs) -> str:
    marker = "__ROUTER_TEXT_FIELD__"
    tmp = tpl.replace("{text}", marker)
    tmp = tmp.replace("{", "{{").replace("}", "}}")
    tmp = tmp.replace(marker, "{text}")
    return tmp.format(**kwargs)
