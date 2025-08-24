"""Adaptive policy configuration for routing, summarization, and budgets.

This module converts a CapabilityReport (from capability_probe.py) into a concrete
set of runtime policies used by the app: context budgeting, summarization
aggressiveness, web-search breadth, and streaming parameters.

Design goals
------------
- Deterministic, side‑effect free mapping from capabilities → knobs
- Safe minimums on low-spec systems; scale up gracefully on high-spec
- Central place for all heuristics and guardrails

How to use
----------
from capability_probe import collect_capabilities
from policy_config import compute_policy

report = collect_capabilities()               # snapshot of host + llama runtime
policy = compute_policy(report)               # PolicyBundle

# Example: sizing a generation
safe_out, prompt_est = policy.inference.clamp_for_ctx(
    prompt_tokens_est, requested_out_tokens
)

# Example: how many sources to fetch
k = policy.web.search_k

You can pass user/admin overrides to compute_policy(overrides=...).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

# Optional: tolerate absence if capability_probe isn't wired yet
try:
    from capability_probe import CapabilityReport
except Exception:  # pragma: no cover
    @dataclass
    class CapabilityReport:  # minimal shim
        cpu_logical: int = 4
        cpu_score: float = 1.0
        ram_total_gb: float = 8.0
        vram_total_gb: Optional[float] = None
        gpu_backend: str = "none"
        llama: Dict[str, Any] | None = None


# -------------------------------
# Policy data classes
# -------------------------------

@dataclass
class InferencePolicy:
    # Context/budgeting
    n_ctx: int
    margin_tokens: int
    max_out_tokens_default: int

    def clamp_for_ctx(self, prompt_tokens_est: int, requested_out: int) -> tuple[int, int]:
        """Return (safe_out, prompt_tokens_est) with margin enforcement.
        Matches services/context_window.clamp_out_budget, but centralized.
        """
        n_ctx = max(512, int(self.n_ctx))
        margin = max(16, int(self.margin_tokens))
        prompt = max(0, int(prompt_tokens_est or 0))
        available = max(16, n_ctx - prompt - margin)
        safe_out = max(16, min(int(requested_out or self.max_out_tokens_default), available))
        return safe_out, prompt


@dataclass
class SummarizationPolicy:
    # How aggressively we roll older turns into the summary
    # Higher = more aggressive summarization (peel more turns per rollup)
    aggressiveness: int  # 1..5
    # Max number of tail turns kept verbatim before summarization kicks in
    tail_turns: int
    # Router text budgets
    router_summary_chars: int
    router_max_chars: int


@dataclass
class WebPolicy:
    # Search breadth (number of sources to fetch)
    search_k: int
    # Fetch parallelism & timeouts (seconds)
    fetch_parallel: int
    per_url_timeout_s: float
    # Total assembled web block character budget
    total_char_budget: int
    per_doc_char_budget: int


@dataclass
class RouterPolicy:
    # Whether to even attempt live web
    enable_auto_web: bool


@dataclass
class PolicyBundle:
    inference: InferencePolicy
    summarization: SummarizationPolicy
    web: WebPolicy
    router: RouterPolicy

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inference": asdict(self.inference),
            "summarization": asdict(self.summarization),
            "web": asdict(self.web),
            "router": asdict(self.router),
        }


# -------------------------------
# Tiering helpers
# -------------------------------

def _vram_tier(vram_gb: Optional[float]) -> str:
    if not vram_gb or vram_gb <= 0.0:
        return "none"
    if vram_gb < 4:
        return "tiny"
    if vram_gb < 8:
        return "small"
    if vram_gb < 16:
        return "mid"
    if vram_gb < 24:
        return "large"
    return "xl"


def _cpu_tier(threads: int, cpu_score: float) -> str:
    t = max(1, threads)
    # cpu_score is an abstracted 0.0..N measure; we blend both
    eff = (t * max(0.5, cpu_score))
    if eff < 6:
        return "low"
    if eff < 16:
        return "mid"
    if eff < 32:
        return "high"
    return "ultra"


# -------------------------------
# Main mapping logic
# -------------------------------

def compute_policy(report: CapabilityReport, overrides: Optional[Dict[str, Any]] = None) -> PolicyBundle:
    """Map host+runtime capability → policies.

    The mapping is intentionally conservative and monotonic: higher VRAM/CPU
    never reduces budgets, only raises them within safe bounds.
    """
    overrides = overrides or {}

    # Derive tiers
    llama_cfg = (report.llama or {}).get("config", {}) if isinstance(report.llama, dict) else {}
    n_ctx = int(llama_cfg.get("nCtx" , 4096))
    n_threads = int(llama_cfg.get("nThreads" , report.cpu_logical or 4))

    vram_gb = report.vram_total_gb
    vram = _vram_tier(vram_gb)
    cpu = _cpu_tier(n_threads, float(getattr(report, "cpu_score", 1.0) or 1.0))

    # ---------------- Inference policy ----------------
    # Margin scales slightly with ctx to reduce overflow retries
    if n_ctx <= 2048:
        margin = 64
        default_out = 256
    elif n_ctx <= 4096:
        margin = 64
        default_out = 384
    elif n_ctx <= 8192:
        margin = 96
        default_out = 512
    else:
        margin = 128
        default_out = 768

    inference = InferencePolicy(
        n_ctx=n_ctx,
        margin_tokens=overrides.get("margin_tokens", margin),
        max_out_tokens_default=overrides.get("max_out_tokens_default", default_out),
    )

    # ---------------- Summarization policy ----------------
    # Base values
    tail_turns = 6
    router_summary_chars = 600
    router_max_chars = 1400
    aggr = 2

    # Scale with capabilities: bigger ctx/VRAM → keep more tail, less aggressive
    if n_ctx >= 8192 or vram in {"mid", "large", "xl"}:
        tail_turns = 8
        aggr = 2
        router_summary_chars = 900
        router_max_chars = 1800
    if n_ctx >= 12288 or vram in {"large", "xl"}:
        tail_turns = 10
        aggr = 1
        router_summary_chars = 1200
        router_max_chars = 2200

    # But clamp if CPU is very weak (router/summarizer are model calls)
    if cpu == "low":
        aggr = max(aggr, 3)
        router_summary_chars = min(router_summary_chars, 800)
        router_max_chars = min(router_max_chars, 1600)

    summarization = SummarizationPolicy(
        aggressiveness=overrides.get("summarize_aggressiveness", aggr),
        tail_turns=overrides.get("tail_turns", tail_turns),
        router_summary_chars=overrides.get("router_summary_chars", router_summary_chars),
        router_max_chars=overrides.get("router_max_chars", router_max_chars),
    )

    # ---------------- Web policy ----------------
    # Start conservative to avoid prompt bloat; scale with tiers
    search_k = 2
    fetch_parallel = 2
    per_url_timeout_s = 8.0
    total_char_budget = 1600
    per_doc_char_budget = 900

    if vram in {"mid", "large", "xl"} or cpu in {"high", "ultra"}:
        search_k = 3
        fetch_parallel = 3
        total_char_budget = 2000
        per_doc_char_budget = 1100
    if vram in {"large", "xl"} and cpu in {"high", "ultra"}:
        search_k = 4
        fetch_parallel = 4
        per_url_timeout_s = 10.0
        total_char_budget = 2400
        per_doc_char_budget = 1200

    web = WebPolicy(
        search_k=int(overrides.get("search_k", search_k)),
        fetch_parallel=int(overrides.get("fetch_parallel", fetch_parallel)),
        per_url_timeout_s=float(overrides.get("per_url_timeout_s", per_url_timeout_s)),
        total_char_budget=int(overrides.get("total_char_budget", total_char_budget)),
        per_doc_char_budget=int(overrides.get("per_doc_char_budget", per_doc_char_budget)),
    )

    # ---------------- Router policy ----------------
    enable_auto_web = True
    # On extremely weak devices, you might want to default off
    if cpu == "low" and vram in {"none", "tiny"}:
        enable_auto_web = True  # keep on but rely on small k/timeouts

    router = RouterPolicy(enable_auto_web=overrides.get("enable_auto_web", enable_auto_web))

    return PolicyBundle(
        inference=inference,
        summarization=summarization,
        web=web,
        router=router,
    )


# -------------------------------
# Small utility: pretty debug line
# -------------------------------

def debug_line(policy: PolicyBundle) -> str:
    p = policy.to_dict()
    inf = p["inference"]; summ = p["summarization"]; web = p["web"]; r = p["router"]
    return (
        f"INF[n_ctx={inf['n_ctx']}, margin={inf['margin_tokens']}, out_def={inf['max_out_tokens_default']}] "
        f"SUMM[aggr={summ['aggressiveness']}, tail={summ['tail_turns']}, rs={summ['router_summary_chars']}, rmax={summ['router_max_chars']}] "
        f"WEB[k={web['search_k']}, par={web['fetch_parallel']}, t={web['per_url_timeout_s']}s, T={web['total_char_budget']}, per={web['per_doc_char_budget']}] "
        f"ROUTER[auto={r['enable_auto_web']}]"
    )
