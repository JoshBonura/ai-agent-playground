# aimodel/file_read/services/streaming_worker.py
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator

from ..core.logging import get_logger
from ..core.settings import SETTINGS
from ..utils.streaming import (
    RUNJSON_END,
    RUNJSON_START,
    build_run_json,
    collect_engine_timings,
    watch_disconnect,
)

log = get_logger(__name__)


def _preview(s: str, n: int = 80) -> str:
    """single-line preview for log lines."""
    try:
        s = s.replace("\n", "\\n")
    except Exception:
        pass
    return (s[:n] + "…") if len(s) > n else s


async def run_stream(
    *,
    llm,
    messages,
    out_budget,
    stop_ev,
    request,
    temperature: float,
    top_p: float,
    input_tokens_est: int | None,
    t0_request: float | None = None,
    budget_view: dict | None = None,
    emit_stats: bool = True,
    worker_meta: dict | None = None, 
) -> AsyncGenerator[bytes, None]:
    """
    Thread-safe async streamer:
      - Runs the model's streaming call in a background thread
      - Bridges data into an asyncio.Queue using run_coroutine_threadsafe
      - Yields bytes to the client
    """
    # Entry diagnostics
    log.info(
        "[run] enter emit_stats=%s runjson_emit_setting=%s q_max=%s top_k=%s repeat_penalty=%s",
        emit_stats,
        bool(SETTINGS.runjson_emit),
        SETTINGS.stream_queue_maxsize,
        SETTINGS.stream_top_k,
        SETTINGS.stream_repeat_penalty,
    )

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=SETTINGS.stream_queue_maxsize)
    SENTINEL = object()

    # Bridge puts from the producer thread into the event loop queue safely.
    def put_sync(item) -> None:
        timeout = getattr(SETTINGS, "stream_queue_thread_put_timeout_sec", 30)
        fut = asyncio.run_coroutine_threadsafe(q.put(item), loop)
        # Block the producer thread until the item is enqueued (bounded by timeout)
        fut.result(timeout=timeout)

    def produce():
        t_start = t0_request or time.perf_counter()
        t_first: float | None = None
        t_last: float | None = None
        t_call: float | None = None
        finish_reason: str | None = None
        err_text: str | None = None
        out_parts: list[str] = []
        stage: dict = {"queueWaitSec": None, "genSec": None}

        try:
            # Create the model stream (may block; done in this worker thread)
            try:
                t_call = time.perf_counter()
                log.info(
                    "[run] model.call max_tokens=%s temp=%.3f top_p=%.3f stops=%s",
                    out_budget,
                    temperature,
                    top_p,
                    SETTINGS.stream_stop_strings,
                )
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
                # Retry with fewer tokens on context overflow
                if "exceed context window" in str(ve).lower():
                    retry_tokens = max(
                        SETTINGS.stream_retry_min_tokens,
                        int(out_budget * SETTINGS.stream_retry_fraction),
                    )
                    log.warning(
                        "[run] context overflow; retrying with max_tokens=%d (was %d)",
                        retry_tokens,
                        out_budget,
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
                    log.info("[run] stop_ev set; breaking producer loop")
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

                # fine-grained piece preview
                try:
                    log.debug(
                        "[run] piece len=%d total_so_far=%d preview='%s'",
                        len(piece),
                        sum(len(p) for p in out_parts),
                        _preview(piece),
                    )
                except Exception:
                    pass

                # Backpressure: block briefly if queue is full, until we can put
                while not stop_ev.is_set():
                    try:
                        put_sync(piece)
                        break
                    except Exception as _e:
                        log.warning("[run] backpressure; retrying put_sync: %s", _e)
                        time.sleep(SETTINGS.stream_backpressure_sleep_sec)

        except Exception as e:
            err_text = str(e)
            log.exception("generate: llm stream error: %s", e)
            try:
                put_sync(f"[aimodel] error: {e}")
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

                # Collect engine timings (llama.cpp etc.)
                try:
                    engine = collect_engine_timings(llm)
                except Exception:
                    engine = None
                if engine:
                    stage["engine"] = engine

                # Build runjson payload
                run_json = build_run_json(
                    request_cfg={
                        "temperature": temperature,
                        "top_p": top_p,
                        "max_tokens": out_budget,
                    },
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
                    worker_meta=worker_meta,
                )

                # gate + append diagnostics
                if SETTINGS.runjson_emit and emit_stats:
                    try:
                        payload = RUNJSON_START + json.dumps(run_json) + RUNJSON_END
                        log.info(
                            "[run] runjson.append size=%d out_len=%d ttft=%.3fs gen=%.3fs",
                            len(payload),
                            len(out_text or ""),
                            float(stage.get("ttftSec") or 0.0),
                            float(stage.get("genSec") or 0.0),
                        )
                        put_sync(payload)
                    except Exception as e:
                        log.error("[run] runjson.append failed: %s", e)
                else:
                    log.info(
                        "[run] runjson.skipped runjson_emit=%s emit_stats=%s",
                        bool(SETTINGS.runjson_emit),
                        bool(emit_stats),
                    )
            except Exception:
                log.exception("[run] finalize error while building/appending runjson")
            finally:
                try:
                    llm.reset()
                except Exception:
                    pass
                try:
                    put_sync(SENTINEL)
                except Exception:
                    pass

    disconnect_task = asyncio.create_task(watch_disconnect(request, stop_ev))
    producer = asyncio.create_task(asyncio.to_thread(produce))

    try:
        while True:
            item = await q.get()
            if item is SENTINEL:
                log.info("[run] sentinel received; consumer exiting")
                break

            # Log chunk boundaries + marker presence
            try:
                if isinstance(item, (bytes, bytearray)):
                    s = None
                    try:
                        s = item.decode("utf-8", errors="ignore")
                    except Exception:
                        s = None
                    if s:
                        has_start = RUNJSON_START in s
                        has_end = RUNJSON_END in s
                        if has_start or has_end:
                            log.info(
                                "[run] consumer chunk contains marker start=%s end=%s len=%d",
                                has_start,
                                has_end,
                                len(s),
                            )
                        else:
                            log.debug("[run] consumer chunk len=%d preview='%s'", len(s), _preview(s))
                else:
                    # string chunk
                    s = str(item)
                    if RUNJSON_START in s or RUNJSON_END in s:
                        log.info(
                            "[run] consumer chunk contains marker (str) start=%s end=%s len=%d",
                            RUNJSON_START in s,
                            RUNJSON_END in s,
                            len(s),
                        )
                    else:
                        log.debug("[run] consumer chunk len=%d preview='%s'", len(s), _preview(s))
            except Exception:
                pass

            yield (item if isinstance(item, bytes) else item.encode("utf-8"))

        if stop_ev.is_set() and SETTINGS.stream_emit_stopped_line:
            yield (f"\n{SETTINGS.stopped_line_marker}\n").encode()
    finally:
        try:
            stop_ev.set()
        except Exception:
            pass
        try:
            disconnect_task.cancel()
        except Exception:
            pass
        try:
            await asyncio.wait_for(producer, timeout=SETTINGS.stream_producer_join_timeout_sec)
        except Exception:
            log.warning("[run] producer join timed out")
