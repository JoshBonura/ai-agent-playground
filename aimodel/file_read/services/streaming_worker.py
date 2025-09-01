# aimodel/file_read/services/streaming_worker.py
from __future__ import annotations
import asyncio, json, time, logging
from typing import AsyncGenerator, Optional, List

from ..core.settings import SETTINGS
from ..utils.streaming import (
    RUNJSON_START, RUNJSON_END,
    build_run_json, watch_disconnect,
)

log = logging.getLogger("aimodel.api.generate")

async def run_stream(
    *, llm, messages, out_budget, stop_ev, request,
    temperature: float, top_p: float, input_tokens_est: Optional[int],  t0_request: Optional[float] = None, budget_view: Optional[dict] = None,
) -> AsyncGenerator[bytes, None]:
    q: asyncio.Queue = asyncio.Queue(maxsize=SETTINGS.stream_queue_maxsize)
    SENTINEL = object()

    def produce():
        t_start = t0_request or time.perf_counter()
        t_first: Optional[float] = None
        t_last: Optional[float] = None
        t_call: Optional[float] = None
        finish_reason: Optional[str] = None
        err_text: Optional[str] = None
        out_parts: List[str] = []
        stage: dict = {"queueWaitSec": None, "genSec": None}

        try:
            try:
                t_call = time.perf_counter()
                stream = llm.create_chat_completion(
                    messages=messages,
                    stream=True,
                    max_tokens=out_budget,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=SETTINGS.stream_top_k,
                    repeat_penalty=SETTINGS.stream_repeat_penalty,
                    stop=SETTINGS.stream_stop_strings,
                )
            except ValueError as ve:
                if "exceed context window" in str(ve).lower():
                    retry_tokens = max(
                        SETTINGS.stream_retry_min_tokens,
                        int(out_budget * SETTINGS.stream_retry_fraction)
                    )
                    log.warning(
                        "generate: context overflow, retrying with max_tokens=%d",
                        retry_tokens
                    )
                    stream = llm.create_chat_completion(
                        messages=messages,
                        stream=True,
                        max_tokens=retry_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        top_k=SETTINGS.stream_top_k,
                        repeat_penalty=SETTINGS.stream_repeat_penalty,
                        stop=SETTINGS.stream_stop_strings,
                    )
                else:
                    raise

            for chunk in stream:
                if stop_ev.is_set():
                    break

                try:
                    fr = chunk["choices"][0].get("finish_reason")
                    if fr:
                        finish_reason = fr
                except Exception:
                    pass

                piece = chunk["choices"][0]["delta"].get("content", "")
                if not piece:
                    continue

                now = time.perf_counter()
                if t_first is None:
                    t_first = now
                t_last = now
                out_parts.append(piece)

                while not stop_ev.is_set():
                    try:
                        q.put_nowait(piece)
                        break
                    except asyncio.QueueFull:
                        time.sleep(SETTINGS.stream_backpressure_sleep_sec)

        except Exception as e:
            err_text = str(e)
            log.exception("generate: llm stream error: %s", e)
            try:
                q.put_nowait(f"[aimodel] error: {e}")
            except Exception:
                pass
        finally:
            try:
                out_text = "".join(out_parts)

                if t_first is not None and t_last is not None:
                    stage["genSec"] = round(t_last - t_first, 3)
                if t_start is not None and t_first is not None:
                    stage["ttftSec"] = round(t_first - t_start, 3)
                if t_start is not None and t_last is not None:
                    stage["totalSec"] = round(t_last - t_start, 3)

                if t_call is not None and t_start is not None:
                    stage["preModelSec"] = round(t_call - t_start, 6)
                if t_call is not None and t_first is not None:
                    stage["modelQueueSec"] = round(t_first - t_call, 6)

                if isinstance(budget_view, dict) and "queueWaitSec" in budget_view:
                    stage["queueWaitSec"] = budget_view.get("queueWaitSec")

                engine = None
                method_used = None
                try:
                    td = None
                    g_last = getattr(llm, "get_last_timings", None)
                    if callable(g_last):
                        method_used = "get_last_timings"
                        td = g_last()
                    if td is None:
                        g = getattr(llm, "get_timings", None)
                        if callable(g):
                            method_used = "get_timings"
                            td = g()
                    if td is None:
                        if isinstance(getattr(llm, "timings", None), dict):
                            method_used = "timings_attr"
                            td = getattr(llm, "timings")
                        elif isinstance(getattr(llm, "perf", None), dict):
                            method_used = "perf_attr"
                            td = getattr(llm, "perf")

                    if isinstance(td, dict):
                        def fms(v):
                            try:
                                return float(v) / 1000.0
                            except Exception:
                                return None
                        def to_i(v):
                            try:
                                return int(v)
                            except Exception:
                                return None
                        load_ms = td.get("load_ms") or td.get("loadMs")
                        prompt_ms = td.get("prompt_ms") or td.get("promptMs") or td.get("prefill_ms")
                        eval_ms = td.get("eval_ms") or td.get("evalMs") or td.get("decode_ms")
                        prompt_n = td.get("prompt_n") or td.get("promptN") or td.get("prompt_tokens")
                        eval_n = td.get("eval_n") or td.get("evalN") or td.get("eval_tokens")
                        engine = {}
                        x = fms(load_ms)
                        if x is not None:
                            engine["loadSec"] = round(x, 3)
                        x = fms(prompt_ms)
                        if x is not None:
                            engine["promptSec"] = round(x, 3)
                        x = fms(eval_ms)
                        if x is not None:
                            engine["evalSec"] = round(x, 3)
                        n = to_i(prompt_n)
                        if n is not None:
                            engine["promptN"] = n
                        n = to_i(eval_n)
                        if n is not None:
                            engine["evalN"] = n
                        try:
                            log.debug("llm timings method=%s keys=%s", method_used, list(td.keys()))
                        except Exception:
                            pass
                    else:
                        log.debug("llm timings unavailable")
                except Exception as e:
                    log.debug("llm timings probe error: %s", e)
                    engine = None
                if engine:
                    stage["engine"] = engine

                if isinstance(budget_view, dict):
                    ttft_val = float(stage.get("ttftSec") or 0.0)
                    pack = (budget_view.get("pack") or {})
                    rag = (budget_view.get("rag") or {})
                    web_bd = ((budget_view.get("web") or {}).get("breakdown") or {})
                    pack_sec = float(pack.get("packSec") or 0.0)
                    trim_sec = float(pack.get("finalTrimSec") or 0.0)
                    comp_sec = float(pack.get("compressSec") or 0.0)
                    rag_router = float(rag.get("routerDecideSec") or 0.0)
                    rag_block = float(
                        rag.get("injectBuildSec")
                        or rag.get("blockBuildSec")
                        or rag.get("sessionOnlyBuildSec")
                        or 0.0
                    )
                    prep_sec = float(web_bd.get("prepSec") or 0.0)
                    web_pre = float(web_bd.get("totalWebPreTtftSec") or 0.0)
                    model_queue = float(stage.get("modelQueueSec") or 0.0)
                    pre_accounted = pack_sec + trim_sec + comp_sec + rag_router + rag_block + web_pre + prep_sec + model_queue
                    unattr_ttft = max(0.0, ttft_val - pre_accounted)
                    budget_view.setdefault("breakdown", {})
                    budget_view["breakdown"].update({
                        "ttftSec": ttft_val,
                        "preTtftAccountedSec": round(pre_accounted, 6),
                        "unattributedTtftSec": round(unattr_ttft, 6),
                    })

                run_json = build_run_json(
                    request_cfg={"temperature": temperature, "top_p": top_p, "max_tokens": out_budget},
                    out_text=out_text,
                    t_start=t_start,
                    t_first=t_first,
                    t_last=t_last,
                    stop_set=stop_ev.is_set(),
                    finish_reason=finish_reason,
                    input_tokens_est=input_tokens_est,
                    budget_view=budget_view,
                    extra_timings=stage,
                    error_text=err_text,
                )
                if SETTINGS.runjson_emit:
                    q.put_nowait(RUNJSON_START + json.dumps(run_json) + RUNJSON_END)
            except Exception:
                pass
            finally:
                try:
                    llm.reset()
                except Exception:
                    pass
                try:
                    q.put_nowait(SENTINEL)
                except Exception:
                    pass

    disconnect_task = asyncio.create_task(watch_disconnect(request, stop_ev))
    producer = asyncio.create_task(asyncio.to_thread(produce))

    try:
        while True:
            item = await q.get()
            if item is SENTINEL:
                break
            yield (item if isinstance(item, bytes) else item.encode("utf-8"))
        if stop_ev.is_set() and SETTINGS.stream_emit_stopped_line:
            yield (f"\n{SETTINGS.stopped_line_marker}\n").encode("utf-8")
    finally:
        stop_ev.set()
        disconnect_task.cancel()
        try:
            await asyncio.wait_for(producer, timeout=SETTINGS.stream_producer_join_timeout_sec)
        except Exception:
            pass
