# aimodel/file_read/services/streaming_worker.py
from __future__ import annotations
import asyncio, json, time, logging
from typing import AsyncGenerator, Optional, List
from ..utils.streaming import (
    RUNJSON_START, RUNJSON_END, STOP_STRINGS,
    build_run_json, watch_disconnect,
)

log = logging.getLogger("aimodel.api.generate")

async def run_stream(
    *, llm, messages, out_budget, stop_ev, request,
    temperature: float, top_p: float, input_tokens_est: Optional[int]
) -> AsyncGenerator[bytes, None]:
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    SENTINEL = object()

    def produce():
        t_start = time.perf_counter()
        t_first: Optional[float] = None
        t_last: Optional[float] = None
        finish_reason: Optional[str] = None
        err_text: Optional[str] = None
        out_parts: List[str] = []

        try:
            try:
                stream = llm.create_chat_completion(
                    messages=messages,
                    stream=True,
                    max_tokens=out_budget,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=40,
                    repeat_penalty=1.25,
                    stop=STOP_STRINGS,
                )
            except ValueError as ve:
                if "exceed context window" in str(ve).lower():
                    retry_tokens = max(64, out_budget // 2)
                    log.warning("generate: context overflow, retrying with max_tokens=%d", retry_tokens)
                    stream = llm.create_chat_completion(
                        messages=messages,
                        stream=True,
                        max_tokens=retry_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        top_k=40,
                        repeat_penalty=1.25,
                        stop=STOP_STRINGS,
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
                        time.sleep(0.005)

        except Exception as e:
            err_text = str(e)
            log.exception("generate: llm stream error: %s", e)
            try:
                q.put_nowait(f"[aimodel] error: {e}")
            except Exception:
                pass
        finally:
            try:
                llm.reset()
            except Exception:
                pass

            try:
                out_text = "".join(out_parts)
                run_json = build_run_json(
                    request_cfg={"temperature": temperature, "top_p": top_p, "max_tokens": out_budget},
                    out_text=out_text,
                    t_start=t_start,
                    t_first=t_first,
                    t_last=t_last,
                    stop_set=stop_ev.is_set(),
                    finish_reason=finish_reason,
                    input_tokens_est=input_tokens_est,
                )
                q.put_nowait(RUNJSON_START + json.dumps(run_json) + RUNJSON_END)
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
            if stop_ev.is_set():
                break
            yield (item if isinstance(item, bytes) else item.encode("utf-8"))
        if stop_ev.is_set():
            yield b"\n\u23F9 stopped\n"
    finally:
        stop_ev.set()
        disconnect_task.cancel()
        try:
            await asyncio.wait_for(producer, timeout=2.0)
        except Exception:
            pass
