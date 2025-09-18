# aimodel/file_read/utils/streaming.py
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from ..core.logging import get_logger
from ..runtime.model_runtime import current_model_info  # ← keep only this import

log = get_logger(__name__)

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


def safe_token_count_messages(llm: Any, msgs: list[dict[str, str]]) -> int:
    return sum(safe_token_count_text(llm, (m.get("content") or "")) for m in msgs)


def model_ident_and_cfg() -> tuple[str, dict[str, object]]:
    info = current_model_info() or {}
    cfg = (info.get("config") or {}) if isinstance(info, dict) else {}
    model_path = cfg.get("modelPath") or ""
    ident = Path(model_path).name or "local-gguf"
    return ident, cfg


def derive_stop_reason(stop_set: bool, finish_reason: str | None, err_text: str | None) -> str:
    if stop_set:
        return "user_cancel"
    if finish_reason:
        return "eosFound" if finish_reason == "stop" else f"finish:{finish_reason}"
    if err_text:
        return "error"
    return "end_of_stream"


def _first(obj: dict, keys: list[str]):
    for k in keys:
        if k in obj and obj[k] is not None:
            return obj[k]
    return None


def _sec_from_ms(v: Any) -> float | None:
    try:
        x = float(v)
        return round(x / 1000.0, 6)
    except Exception:
        return None


def collect_engine_timings(llm: Any) -> dict[str, float | None] | None:
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

    out: dict[str, float | None] = {
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
    request_cfg: dict[str, object],
    out_text: str,
    t_start: float,
    t_first: float | None,
    t_last: float | None,
    stop_set: bool,
    finish_reason: str | None,
    input_tokens_est: int | None,
    budget_view: dict | None = None,
    extra_timings: dict | None = None,
    error_text: str | None = None,
    llm: Any | None = None,  # ← accept llm optionally
) -> dict[str, object]:
    # Resolve llm at call time if not provided to avoid stale imports when running in a worker
    if llm is None:
        from ..runtime import model_runtime as MR  # dynamic import to pick up worker patch
        llm = MR.get_llm()

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

    encode_t = float(input_tokens_est or 0.0)
    decode_t = float(out_tokens or 0.0)
    total_t = encode_t + decode_t
    model_queue_s = float(timings_payload.get("modelQueueSec") or 0.0)
    engine_prompt_s = float((timings_payload.get("engine") or {}).get("promptSec") or 0.0)
    encode_sec = model_queue_s or engine_prompt_s or 0.0
    decode_sec = float(gen_secs or 0.0)
    total_sec = float(t_end - t_start)
    encode_tps = (encode_t / encode_sec) if encode_sec > 0 else None
    decode_tps = (decode_t / decode_sec) if decode_sec > 0 else None
    overall_tps = (total_t / total_sec) if total_sec > 0 else None

    bv = budget_view or {}
    bv_break = (bv.get("breakdown") or {}) if isinstance(bv, dict) else {}
    web = (bv.get("web") or {}) if isinstance(bv, dict) else {}
    web_bd = (web.get("breakdown") or {}) if isinstance(web, dict) else {}
    rag = (bv.get("rag") or {}) if isinstance(bv, dict) else {}

    nctx = bv.get("modelCtx") or bv.get("n_ctx") or 0
    clamp = bv.get("clampMargin") or bv.get("clamp_margin") or 0
    inp_est = bv.get("inputTokensEst") or bv.get("input_tokens_est") or (input_tokens_est or 0)
    out_chosen = bv.get("outBudgetChosen") or bv.get("clamped_out_tokens") or 0
    out_actual = out_tokens
    out_shown = out_actual or out_chosen
    used_ctx = (inp_est or 0) + (out_shown or 0) + (clamp or 0)
    ctx_pct = (float(used_ctx) / float(nctx) * 100.0) if nctx else 0.0

    rag_delta = 0
    for k in ("ragTokensAdded", "blockTokens", "blockTokensApprox", "sessionOnlyTokensApprox"):
        v = rag.get(k)
        if isinstance(v, (int, float)) and v > 0:
            rag_delta = int(v)
            break
    rag_pct_of_input = int(round((rag_delta / inp_est) * 100)) if inp_est else 0

    web_pre = (
        web_bd.get("totalWebPreTtftSec")
        or (
            (web.get("elapsedSec") or 0)
            + (web.get("fetchElapsedSec") or 0)
            + (web.get("injectElapsedSec") or 0)
        )
        or 0
    )

    pre_accounted = bv_break.get("preTtftAccountedSec")
    unattributed = (
        bv_break.get("unattributedTtftSec")
        if "unattributedTtftSec" in bv_break
        else (max(0.0, (ttft_ms / 1000.0) - float(pre_accounted)))
        if pre_accounted is not None
        else None
    )

    return {
        "indexedModelIdentifier": ident,
        "identifier": ident,
        "loadModelConfig": {
            "fields": [
                {"key": "llm.load.llama.cpuThreadPoolSize", "value": int(cfg.get("nThreads") or 0)},
                {"key": "llm.load.contextLength", "value": int(cfg.get("nCtx") or 4096)},
                {
                    "key": "llm.load.llama.acceleration.offloadRatio",
                    "value": 1 if int(cfg.get("nGpuLayers") or 0) > 0 else 0,
                },
                {"key": "llm.load.llama.nBatch", "value": int(cfg.get("nBatch") or 0)},
                {"key": "llm.load.ropeFreqBase", "value": cfg.get("ropeFreqBase")},
                {"key": "llm.load.ropeFreqScale", "value": cfg.get("ropeFreqScale")},
            ]
        },
        "predictionConfig": {
            "fields": [
                {"key": "llm.prediction.temperature", "value": request_cfg.get("temperature", 0.6)},
                {"key": "llm.prediction.topKSampling", "value": 40},
                {
                    "key": "llm.prediction.topPSampling",
                    "value": {"checked": True, "value": request_cfg.get("top_p", 0.9)},
                },
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
        "_derived": {
            "context": {
                "modelCtx": nctx,
                "clampMargin": clamp,
                "inputTokensEst": inp_est,
                "outBudgetChosen": out_chosen,
                "outActual": out_actual,
                "outShown": out_shown,
                "usedCtx": used_ctx,
                "ctxPct": ctx_pct,
            },
            "rag": {
                "ragDelta": rag_delta,
                "ragPctOfInput": rag_pct_of_input,
            },
            "web": {
                "webPre": web_pre,
            },
            "timing": {
                "accountedPreTtftSec": pre_accounted,
                "unattributedPreTtftSec": unattributed,
                "preModelSec": timings_payload.get("preModelSec"),
                "modelQueueSec": timings_payload.get("modelQueueSec"),
                "genSec": gen_secs,
                "ttftSec": round((ttft_ms or 0) / 1000.0, 3),
            },
            "throughput": {
                "encodeTokPerSec": encode_tps,
                "decodeTokPerSec": decode_tps,
                "overallTokPerSec": overall_tps,
            },
        },
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
