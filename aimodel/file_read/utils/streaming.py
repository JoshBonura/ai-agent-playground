from __future__ import annotations
import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..runtime.model_runtime import current_model_info, get_llm

RUNJSON_START = "\n[[RUNJSON]]\n"
RUNJSON_END = "\n[[/RUNJSON]]\n"

STOP_STRINGS = ["</s>", "User:", "\nUser:"]

def strip_runjson(s: str) -> str:
    if not isinstance(s, str) or not s:
        return s
    out, i = [], 0
    while True:
        start = s.find(RUNJSON_START, i)
        if start == -1:
            out.append(s[i:])
            break
        out.append(s[i:start])
        end = s.find(RUNJSON_END, start)
        if end == -1:
            break
        i = end + len(RUNJSON_END)
    return "".join(out).strip()

def safe_token_count_text(llm: Any, text: str) -> int:
    try:
        return len(llm.tokenize(text.encode("utf-8")))
    except Exception:
        try:
            return len(llm.tokenize(text, special=True))
        except Exception:
            return max(1, len(text) // 4)

def safe_token_count_messages(llm: Any, msgs: List[Dict[str, str]]) -> int:
    return sum(safe_token_count_text(llm, (m.get("content") or "")) for m in msgs)

def model_ident_and_cfg() -> Tuple[str, Dict[str, object]]:
    info = current_model_info() or {}
    cfg = (info.get("config") or {}) if isinstance(info, dict) else {}
    model_path = cfg.get("modelPath") or ""
    ident = Path(model_path).name or "local-gguf"
    return ident, cfg

def derive_stop_reason(stop_set: bool, finish_reason: Optional[str], err_text: Optional[str]) -> str:
    if stop_set:
        return "user_cancel"
    if finish_reason:
        return "eosFound" if finish_reason == "stop" else f"finish:{finish_reason}"
    if err_text:
        return "error"
    return "end_of_stream"

def _first(obj: dict, keys: List[str]):
    for k in keys:
        if k in obj and obj[k] is not None:
            return obj[k]
    return None

def _sec_from_ms(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return round(x / 1000.0, 6)
    except Exception:
        return None

def collect_engine_timings(llm: Any) -> Optional[Dict[str, Optional[float]]]:
    src = None
    try:
        if hasattr(llm, "get_last_timings") and callable(llm.get_last_timings):
            src = llm.get_last_timings()
        elif hasattr(llm, "get_timings") and callable(llm.get_timings):
            src = llm.get_timings()
        elif hasattr(llm, "timings"):
            t = llm.timings
            src = t() if callable(t) else t
        elif hasattr(llm, "perf"):
            p = llm.perf
            src = p() if callable(p) else p
        elif hasattr(llm, "stats"):
            s = llm.stats
            src = s() if callable(s) else s
        elif hasattr(llm, "get_stats") and callable(llm.get_stats):
            src = llm.get_stats()
    except Exception:
        src = None

    if not isinstance(src, dict):
        return None

    load_ms = _first(src, ["load_ms", "loadMs", "model_load_ms", "load_time_ms"])
    prompt_ms = _first(src, ["prompt_ms", "promptMs", "prompt_eval_ms", "prompt_time_ms", "prefill_ms"])
    eval_ms = _first(src, ["eval_ms", "evalMs", "decode_ms", "eval_time_ms"])
    prompt_n = _first(src, ["prompt_n", "promptN", "prompt_tokens", "n_prompt_tokens"])
    eval_n = _first(src, ["eval_n", "evalN", "eval_tokens", "n_eval_tokens"])

    out: Dict[str, Optional[float]] = {
        "loadSec": _sec_from_ms(load_ms),
        "promptSec": _sec_from_ms(prompt_ms),
        "evalSec": _sec_from_ms(eval_ms),
        "promptN": None,
        "evalN": None,
    }
    try:
        out["promptN"] = int(prompt_n) if prompt_n is not None else None
    except Exception:
        out["promptN"] = None
    try:
        out["evalN"] = int(eval_n) if eval_n is not None else None
    except Exception:
        out["evalN"] = None
    return out

def build_run_json(
    *,
    request_cfg: Dict[str, object],
    out_text: str,
    t_start: float,
    t_first: Optional[float],
    t_last: Optional[float],
    stop_set: bool,
    finish_reason: Optional[str],
    input_tokens_est: Optional[int],
    budget_view: Optional[dict] = None,
    extra_timings: Optional[dict] = None,
    error_text: Optional[str] = None,
) -> Dict[str, object]:
    llm = get_llm()
    out_tokens = safe_token_count_text(llm, out_text)
    t_end = time.perf_counter()
    ttft_ms = ((t_first or t_end) - t_start) * 1000.0
    gen_secs = (t_last - t_first) if (t_first is not None and t_last is not None) else 0.0
    tok_per_sec = (out_tokens / gen_secs) if gen_secs > 0 else None
    stop_reason_final = derive_stop_reason(stop_set, finish_reason, None)
    ident, cfg = model_ident_and_cfg()
    total_tokens = (input_tokens_est or 0) + out_tokens if input_tokens_est is not None else None

    timings_payload = dict(extra_timings or {})
    if "engine" not in timings_payload or timings_payload.get("engine") is None:
        timings_payload["engine"] = collect_engine_timings(llm)

    return {
        "indexedModelIdentifier": ident,
        "identifier": ident,
        "loadModelConfig": {
            "fields": [
                {"key": "llm.load.llama.cpuThreadPoolSize", "value": int(cfg.get("nThreads") or 0)},
                {"key": "llm.load.contextLength", "value": int(cfg.get("nCtx") or 4096)},
                {"key": "llm.load.llama.acceleration.offloadRatio", "value": 1 if int(cfg.get("nGpuLayers") or 0) > 0 else 0},
                {"key": "llm.load.llama.nBatch", "value": int(cfg.get("nBatch") or 0)},
                {"key": "llm.load.ropeFreqBase", "value": cfg.get("ropeFreqBase")},
                {"key": "llm.load.ropeFreqScale", "value": cfg.get("ropeFreqScale")},
            ]
        },
        "predictionConfig": {
            "fields": [
                {"key": "llm.prediction.temperature", "value": request_cfg.get("temperature", 0.6)},
                {"key": "llm.prediction.topKSampling", "value": 40},
                {"key": "llm.prediction.topPSampling", "value": {"checked": True, "value": request_cfg.get("top_p", 0.9)}},
                {"key": "llm.prediction.repeatPenalty", "value": {"checked": True, "value": 1.25}},
                {"key": "llm.prediction.maxTokens", "value": request_cfg.get("max_tokens", 512)},
                {"key": "llm.prediction.stopStrings", "value": STOP_STRINGS},
                {"key": "llm.prediction.llama.cpuThreads", "value": int(cfg.get("nThreads") or 0)},
                {"key": "llm.prediction.contextPrefill", "value": []},
                {"key": "llm.prediction.tools", "value": {"type": "none"}},
                {"key": "llm.prediction.promptTemplate", "value": {"type": "none"}},
            ]
        },
        "stats": {
            "stopReason": stop_reason_final,
            "tokensPerSecond": tok_per_sec,
            "numGpuLayers": int(cfg.get("nGpuLayers") or 0),
            "timeToFirstTokenSec": round((ttft_ms or 0) / 1000.0, 3),
            "totalTimeSec": round(t_end - t_start, 3),
            "promptTokensCount": input_tokens_est,
            "predictedTokensCount": out_tokens,
            "totalTokensCount": total_tokens,
            "budget": budget_view or {},
            "timings": timings_payload,
            "error": error_text or None,
        },
        "budget_view": (budget_view or {}),
    }

async def watch_disconnect(request, stop_ev):
    if await request.is_disconnected():
        stop_ev.set()
        return
    while not stop_ev.is_set():
        await asyncio.sleep(0.2)
        if await request.is_disconnected():
            stop_ev.set()
            break
