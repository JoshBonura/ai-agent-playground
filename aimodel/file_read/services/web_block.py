# aimodel/file_read/services/web_block.py
from __future__ import annotations
import logging, re
from typing import Optional
from ..model_runtime import get_llm
from ..web.orchestrator import build_web_block
from ..web.query_summarizer import summarize_query

log = logging.getLogger("aimodel.api.generate")

async def always_inject_web_block(st, latest_user_text: str, *, k: int):
    """
    EXACT behavior retained:
      1) If [[search: ...]] present -> use that literal query.
      2) Else summarize the user's text into a short query.
      3) Call orchestrator.build_web_block(query) and APPEND the block to st["recent"].
    """
    if not latest_user_text or not latest_user_text.strip():
        return

    m = re.search(r"\[\[search:\s*(.+?)\s*\]\]", latest_user_text, re.I)
    if m:
        query = m.group(1).strip()
        log.info("generate: explicit [[search:]] query=%r", query)
    else:
        try:
            query = summarize_query(get_llm(), latest_user_text.strip())
            short_src = (latest_user_text[:120] + "…") if len(latest_user_text) > 120 else latest_user_text
            log.info("generate: summarized query=%r (from=%r)", query, short_src)
        except Exception as e:
            log.exception("generate: summarize_query failed: %s", e)
            return

    if not query:
        log.warning("generate: empty summarized query, skipping web")
        return

    try:
        block = await build_web_block(query, k=k, per_url_timeout_s=8.0)
        if block:
            # ⬇⬇⬇ store as EPHEMERAL, not in recent
            st.setdefault("_ephemeral_web", []).append({"role": "user", "content": block})
            log.info("generate: injected web block EPHEMERAL (chars=%d)", len(block))
        else:
            log.warning("generate: orchestrator returned no block for query=%r", query)
    except Exception as e:
        log.exception("generate: orchestrator failed for query=%r: %s", query, e)
