from __future__ import annotations

"""
Guardrail / launch-planning logic for llama.cpp workers.

This module computes:
  1) base kwargs + env from SETTINGS (accel, kv_offload, etc)
  2) GPU/VRAM projections and budget
  3) auto-fit of n_gpu_layers
  4) final mutations / decision (proceed / proceed_vmm_allowed / abort)

It exposes a single high-level function:

    compute_llama_settings(model_path: str, user_kwargs: dict | None) -> tuple[dict, dict, dict]

which returns (cleaned_kwargs, env_patch, diag) ready to be used by the supervisor.
"""

import os
import subprocess
from typing import Dict, Tuple

from ..core.logging import get_logger
from ..core.settings import SETTINGS
from ..services.system_snapshot import get_vram_projection

log = get_logger(__name__)


# ----------------------------------------------------------------------
# Low-level helpers (kept here so supervisor.py stays lean)
# ----------------------------------------------------------------------

def _gpu_free_bytes() -> int:
    # NVML if available, else nvidia-smi, else 0
    try:
        import pynvml as nv
        nv.nvmlInit()
        h = nv.nvmlDeviceGetHandleByIndex(0)
        mem = nv.nvmlDeviceGetMemoryInfo(h)
        free_b = int(mem.free)
        nv.nvmlShutdown()
        return free_b
    except Exception:
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL
            ).decode().strip().splitlines()[0]
            return int(out) * 1024 * 1024
        except Exception:
            return 0


def _estimate_kv_bytes(n_ctx: int) -> int:
    # Conservative upper-bound: ~0.125 MB/token (~131072 bytes/token)
    return max(64 * 1024 * 1024, n_ctx * 131072)


# ----------------------------------------------------------------------
# Stage A: read settings and craft base kwargs/env
# ----------------------------------------------------------------------

def _llama_kwargs_from_settings(model_path: str) -> tuple[dict, dict]:
    eff = SETTINGS.effective() or {}
    wd = (eff.get("worker_default") or {}).copy()

    accel_in = (wd.get("accel") or eff.get("hw_backend") or eff.get("hw_accel") or "auto")
    accel_in = str(accel_in).lower().strip()

    # normalize inherited numeric prefs into wd
    if wd.get("device") is None and isinstance(eff.get("hw_cuda_device"), int):
        wd["device"] = int(eff.get("hw_cuda_device"))
    if wd.get("n_gpu_layers") is None and isinstance(eff.get("hw_n_gpu_layers"), int):
        wd["n_gpu_layers"] = int(eff.get("hw_n_gpu_layers"))

    # Prefer explicit UI setting gpu_offload_kv over everything
    if eff.get("gpu_offload_kv") is not None:
        wd["offload_kv_to_gpu"] = bool(eff["gpu_offload_kv"])
    elif wd.get("offload_kv_to_gpu") is None and eff.get("hw_kv_offload") is not None:
        wd["offload_kv_to_gpu"] = bool(eff["hw_kv_offload"])

    log.info(
        "[supervisor.settings] VMM src: wd.limit_offload_to_dedicated_vram=%r eff.gpu_limit_offload_dedicated=%r eff.hw_limit_offload_dedicated=%r",
        wd.get("limit_offload_to_dedicated_vram"),
        eff.get("gpu_limit_offload_dedicated"),
        eff.get("hw_limit_offload_dedicated"),
    )

    if wd.get("limit_offload_to_dedicated_vram") is None:
        if eff.get("gpu_limit_offload_dedicated") is not None:
            wd["limit_offload_to_dedicated_vram"] = bool(eff.get("gpu_limit_offload_dedicated"))
        elif eff.get("hw_limit_offload_dedicated") is not None:
            wd["limit_offload_to_dedicated_vram"] = bool(eff.get("hw_limit_offload_dedicated"))

    device = wd.get("device")
    n_ctx = int(wd.get("n_ctx", 4096))
    n_batch = int(wd.get("n_batch", 256))
    n_threads = wd.get("n_threads")
    n_gpu_layers = wd.get("n_gpu_layers")
    rope_freq_base = wd.get("rope_freq_base")
    rope_freq_scale = wd.get("rope_freq_scale")
    limit_vmm = wd.get("limit_offload_to_dedicated_vram")

    gpuish = {"cuda", "metal", "hip", "rocm"}
    accel_final = accel_in if accel_in in (gpuish | {"cpu", "auto"}) else "auto"
    user_set_gpu_backend = accel_in in gpuish
    user_set_layers = isinstance(n_gpu_layers, int)

    if user_set_gpu_backend:
        if (not user_set_layers) or (isinstance(n_gpu_layers, int) and n_gpu_layers <= 0):
            n_gpu_layers = None  # let guardrails decide

    kwargs: dict = {"model_path": model_path, "n_ctx": n_ctx, "n_batch": n_batch}

    if "n_gpu_layers" not in kwargs and isinstance(n_gpu_layers, int):
        kwargs["n_gpu_layers"] = n_gpu_layers

    if isinstance(n_threads, int):
        kwargs["n_threads"] = n_threads
    if isinstance(n_gpu_layers, int):
        if n_gpu_layers > 0:
            clamped = (max(0, n_gpu_layers) if accel_final == "cpu" else max(1, n_gpu_layers))
            log.info("[supervisor.settings] clamp stage: accel_final=%s raw=%s → %s", accel_final, n_gpu_layers, clamped)
            kwargs["n_gpu_layers"] = clamped
        else:
            log.info("[supervisor.settings] n_gpu_layers=0 (auto); deferring to guardrail auto-fit")

    if isinstance(device, int):
        kwargs["main_gpu"] = device
    if rope_freq_base is not None:
        kwargs["rope_freq_base"] = float(rope_freq_base)
    if rope_freq_scale is not None:
        kwargs["rope_freq_scale"] = float(rope_freq_scale)

    kv_offload_pref = wd.get("offload_kv_to_gpu")

    log.info(
        "[supervisor.settings] PREFS src: wd.offload_kv_to_gpu=%r eff.gpu_offload_kv=%r eff.hw_kv_offload=%r",
        kv_offload_pref, eff.get("gpu_offload_kv"), eff.get("hw_kv_offload"),
    )

    kv_final = bool(kv_offload_pref) and (accel_final in {"cuda", "hip", "metal", "auto"})
    if accel_final == "cpu":
        kv_final = False
    kwargs["kv_offload"] = kv_final

    if kv_offload_pref is False and accel_final in {"cuda", "hip", "metal", "auto"} and kwargs.get("kv_offload") is not False:
        log.warning("[supervisor.settings] EXPECTED kv_offload=False but got %r; check precedence", kwargs.get("kv_offload"))

    env_patch: dict = {"LLAMA_ACCEL": accel_final}
    if accel_final == "cpu":
        kwargs.setdefault("n_gpu_layers", 0)
        env_patch["CUDA_VISIBLE_DEVICES"] = "-1"
        env_patch["HIP_VISIBLE_DEVICES"] = "-1"
        env_patch["LLAMA_NO_METAL"] = "1"
    elif accel_final in {"hip", "rocm"}:
        env_patch["CUDA_VISIBLE_DEVICES"] = "-1"
        env_patch["LLAMA_NO_METAL"] = "1"
    elif accel_final == "metal":
        env_patch["LLAMA_NO_METAL"] = "0"

    if limit_vmm:
        env_patch["GGML_CUDA_NO_VMM"] = "1"
        log.info("[supervisor.settings] VMM limit ON -> GGML_CUDA_NO_VMM=1")
    else:
        log.info("[supervisor.settings] VMM limit OFF -> GGML_CUDA_NO_VMM not set")

    log.info(
        "[supervisor.settings] IN: accel_in=%r device=%r n_gpu_layers_in=%r n_threads=%r n_ctx=%r kv_offload_in=%r limit_vmm_in=%r",
        accel_in, device, wd.get("n_gpu_layers"), n_threads, n_ctx, kv_offload_pref, limit_vmm
    )
    log.info(
        "[supervisor.settings] LEGACY: hw_backend=%r hw_accel=%r hw_cuda_device=%r hw_n_gpu_layers=%r hw_kv_offload=%r gpu_offload_kv=%r hw_limit_offload_dedicated=%r gpu_limit_offload_dedicated=%r",
        eff.get("hw_backend"), eff.get("hw_accel"), eff.get("hw_cuda_device"),
        eff.get("hw_n_gpu_layers"), eff.get("hw_kv_offload"), eff.get("gpu_offload_kv"),
        eff.get("hw_limit_offload_dedicated"), eff.get("gpu_limit_offload_dedicated"),
    )
    log.info(
        "[supervisor.settings] RESOLVED: final_accel=%r user_set_gpu_backend=%r user_set_layers=%r final_n_gpu_layers=%r device=%r",
        accel_final, user_set_gpu_backend, user_set_layers, kwargs.get("n_gpu_layers"), kwargs.get("main_gpu")
    )
    log.info("[supervisor.settings] KV final: pref=%r accel=%s -> kv_offload=%s", kv_offload_pref, accel_final, kv_final)
    log.info("[supervisor.settings] kwargs_out=%s", kwargs)
    log.info("[supervisor.settings] env_patch=%s", env_patch)

    # Log-only quick projection
    try:
        model_sz = os.path.getsize(model_path)
    except Exception:
        model_sz = 0
    total_layers = 32
    _ngl_raw = kwargs.get("n_gpu_layers")
    ngl_eff = total_layers if (_ngl_raw is None or int(_ngl_raw) < 0) else int(_ngl_raw)
    ngl_eff = max(0, min(total_layers, ngl_eff))
    kv_on = bool(kwargs.get("kv_offload"))
    n_ctx = int(kwargs.get("n_ctx", 4096))
    vmm_forced_off = (env_patch.get("GGML_CUDA_NO_VMM") == "1")
    model_gpu_bytes = int(model_sz * (ngl_eff / total_layers)) if total_layers > 0 else 0
    kv_bytes = _estimate_kv_bytes(n_ctx) if kv_on else 0
    overhead_bytes = 200 * 1024 * 1024
    projected_vram = model_gpu_bytes + kv_bytes + overhead_bytes
    free_vram = _gpu_free_bytes()
    headroom = 0.15 if vmm_forced_off else 0.05
    budget = int(free_vram * (1.0 - headroom))
    log.info(
        "[guardrail.logonly] vram_proj=%.2fGB (model=%.2f kv=%.2f ovh=%.2f) free=%.2fGB budget=%.2fGB vmm_forced_off=%s ngl=%d kv_on=%s",
        projected_vram/(1024**3),
        model_gpu_bytes/(1024**3),
        kv_bytes/(1024**3),
        overhead_bytes/(1024**3),
        (free_vram or 0)/(1024**3),
        (budget or 0)/(1024**3),
        vmm_forced_off, ngl_eff, kv_on,
    )
    return kwargs, env_patch


# ----------------------------------------------------------------------
# Stage B: decision
# ----------------------------------------------------------------------

def _guardrail_decide(*, mode: str, custom_gb: float | None, proj_gb: float,
                    free_gb: float, total_gb: float,
                      kv_on: bool, n_gpu_layers: int | None, n_ctx: int,
                      vmm_limit_enabled: bool, kv_user_pref: bool) -> tuple[str, dict, dict]:
    """
    Returns: (action, kwargs_patch, env_patch_patch)
    action in {"proceed", "proceed_vmm_allowed", "abort"}
    """
    mode = (mode or "balanced").lower()

    def budget_for(m):
        if m == "off":      return float("+inf")
        if m == "strict":   return min(max(free_gb - 0.25, 0.0), 0.85 * total_gb)
        if m == "balanced": return min(max(free_gb - 0.15, 0.0), 0.93 * total_gb)
        if m == "relaxed":  return min(max(free_gb - 0.05, 0.0), 0.99 * total_gb)
        if m == "custom" and isinstance(custom_gb, (int, float)):
            return max(float(custom_gb), 0.0)
        return min(max(free_gb - 0.15, 0.0), 0.93 * total_gb)

    budget = budget_for(mode)

    # fast paths
    if proj_gb <= budget:
        env_patch = {"GGML_CUDA_NO_VMM": "1"} if (vmm_limit_enabled and mode != "relaxed") else {}
        return "proceed", {}, env_patch

    if mode == "off":
        return "proceed", {}, {}
    if mode == "relaxed":
        return "proceed_vmm_allowed", {}, {}

    # STRICT or CUSTOM over-budget → abort ladder
    if mode == "strict":
        if kv_on and not kv_user_pref:
            return "proceed", {"offload_kqv": False}, {"GGML_CUDA_NO_VMM": "1"} if vmm_limit_enabled else {}
        if isinstance(n_gpu_layers, int) and n_gpu_layers > 1:
            return "proceed", {"n_gpu_layers": max(1, int(n_gpu_layers * 0.9))}, {"GGML_CUDA_NO_VMM": "1"} if vmm_limit_enabled else {}
        if n_ctx > 2048:
            return "proceed", {"n_ctx": max(2048, int(n_ctx * 0.85))}, {"GGML_CUDA_NO_VMM": "1"} if vmm_limit_enabled else {}
        return "abort", {}, {}

    # BALANCED ladder
    if kv_on and not kv_user_pref:
        return "proceed", {"offload_kqv": False}, {"GGML_CUDA_NO_VMM": "1"} if vmm_limit_enabled else {}
    if isinstance(n_gpu_layers, int) and n_gpu_layers > 1:
        return "proceed", {"n_gpu_layers": max(1, int(n_gpu_layers * 0.8))}, {"GGML_CUDA_NO_VMM": "1"} if vmm_limit_enabled else {}
    if n_ctx > 2048:
        return "proceed", {"n_ctx": max(2048, int(n_ctx * 0.75))}, {"GGML_CUDA_NO_VMM": "1"} if vmm_limit_enabled else {}

    return "abort", {}, {}


# ----------------------------------------------------------------------
# Stage C: high-level planner
# ----------------------------------------------------------------------

async def compute_llama_settings(model_path: str, user_kwargs: dict | None = None) -> tuple[dict, dict, dict]:
    """
    Returns (cleaned_kwargs, env_patch, diag).

    Behavior:
      * Honors your existing guardrail mode (strict/balanced/relaxed/custom).
      * If a budget is exceeded, performs a bounded-spillover loop:
          1) prefer KV on CPU (unless explicitly requested on GPU),
          2) reduce n_gpu_layers just enough to fit,
          3) if KV is still on-GPU and we're over, shrink n_ctx (down to 2048 floor).
      * Stops once the projection fits the budget (or abort ladder would have been used before).
    """
    base_kwargs, env_patch = _llama_kwargs_from_settings(model_path)
    cleaned: Dict = dict(base_kwargs)
    if isinstance(user_kwargs, dict):
        cleaned.update({k: v for k, v in user_kwargs.items() if v is not None})

    # --- detect hard-pins coming from Advanced UI ---
    user_set_layers_hard = bool(
        isinstance(user_kwargs, dict)
        and isinstance(user_kwargs.get("n_gpu_layers"), int)
        and user_kwargs["n_gpu_layers"] > 0
    )
    user_set_kv_hard = bool(
        isinstance(user_kwargs, dict) and (
            "offload_kqv" in user_kwargs or "kv_offload" in user_kwargs
        )
    )
    user_set_ctx_hard = bool(
        isinstance(user_kwargs, dict)
        and isinstance(user_kwargs.get("n_ctx"), int)
        and user_kwargs["n_ctx"] > 0
    )

    if user_set_layers_hard:
        log.info("[guardrail.hard] honoring user n_gpu_layers=%s (no auto-fit / no downsize)",
                 user_kwargs["n_gpu_layers"])
    if user_set_kv_hard:
        log.info("[guardrail.hard] honoring user KV offload=%s (no flip GPU/CPU)",
                 user_kwargs.get("offload_kqv", user_kwargs.get("kv_offload")))
    if user_set_ctx_hard:
        log.info("[guardrail.hard] honoring user n_ctx=%s (no shrink)", user_kwargs["n_ctx"])


    accel = (env_patch.get("LLAMA_ACCEL") or "auto").lower()
    accel_is_cpu = (accel == "cpu") or (env_patch.get("CUDA_VISIBLE_DEVICES") == "-1")
    if accel_is_cpu:
        cleaned["n_gpu_layers"] = 0
        cleaned["offload_kqv"] = False
        log.info("[guardrail.cpu] accel=cpu → skipping VRAM guardrail (model & KV on CPU)")
        diag = {
            "mode": (str((SETTINGS.effective() or {}).get("worker_default", {}).get("guardrail", {}).get("mode") or "balanced").lower()),
            "projGB": 0.0,
            "freeGB": 0.0,
            "totalGB": 0.0,
            "budgetGB": None,
            "kvOn": False,
            "nGpuLayers": 0,
            "nCtx": int(cleaned.get("n_ctx", 4096)),
            "autoFit": True,
            "strictPreferCpuKV": True,
            "suggested": {"tryBalanced": True, "reduceLayersTo": 0, "shrinkCtxTo": 2048, "disableKV": "alreadyOff"},
        }
        return cleaned, env_patch, diag

    eff = SETTINGS.effective() or {}
    wd = (eff.get("worker_default") or {})
    gr = (wd.get("guardrail") or {}).copy()
    flat_mode = (eff.get("hw_guardrails_mode") or "").strip().lower()
    if flat_mode:
        gr["mode"] = flat_mode
    flat_custom = eff.get("hw_guardrails_custom_gb")
    if isinstance(flat_custom, (int, float)):
        gr["custom_gb"] = float(flat_custom)

    mode = str(gr.get("mode") or "balanced").lower()
    custom_gb = gr.get("custom_gb") or gr.get("custom_gb_limit") or gr.get("custom_gb_budget")

    log.info("[guardrail.config] worker_default.guardrail=%r (mode=%s, custom_gb=%r)", gr, mode, custom_gb)

    auto_fit = gr.get("auto_fit")
    if auto_fit is None:
        auto_fit = eff.get("hw_guardrails_autofit")
    if auto_fit is None:
        auto_fit = True

    strict_prefer_cpu_kv = gr.get("strict_prefer_cpu_kv")
    if strict_prefer_cpu_kv is None:
        strict_prefer_cpu_kv = eff.get("hw_guardrails_strict_prefer_cpu_kv")
    if strict_prefer_cpu_kv is None:
        strict_prefer_cpu_kv = True

    log.info("[guardrail.feature] auto_fit=%s strict_prefer_cpu_kv=%s", auto_fit, strict_prefer_cpu_kv)

    try:
        model_sz_bytes = os.path.getsize(model_path)
    except Exception:
        model_sz_bytes = 0

    total_layers = 32
    ngl_in = cleaned.get("n_gpu_layers")

    # If user pinned, force auto_fit off
    if user_set_layers_hard:
        auto_fit = False

    ngl_eff = (
        ngl_in if (isinstance(ngl_in, int) and ngl_in > 0)
        else (total_layers if auto_fit else 0)
    )
    ngl_eff = max(1, min(total_layers, ngl_eff)) if ngl_eff else 0


    n_ctx = int(cleaned.get("n_ctx", 4096))
    kv_on = bool(cleaned.get("kv_offload") or cleaned.get("offload_kqv"))

    def _per_layer_gb() -> float:
        full_gb = (model_sz_bytes or 0) / (1024**3)
        return (full_gb / total_layers) if total_layers > 0 else 0.0

    def _kv_gb(_nctx: int, _kv_on: bool) -> float:
        return (_estimate_kv_bytes(_nctx) / (1024**3)) if _kv_on else 0.0

    per_layer_gb = _per_layer_gb()

    # first projection (may be coarse)
    model_gb = per_layer_gb * (ngl_eff or 0)
    kv_gb = _kv_gb(n_ctx, kv_on)
    proj_gb, free_gb, total_gb = await get_vram_projection(model_gb, kv_gb, overhead_gb=0.2)

        # Resolve whether KV-on-GPU is an explicit user preference (pin)
    kv_user_pref = False
    try:
        kv_user_pref = bool(
            (eff.get("gpu_offload_kv") is True) or
            (wd.get("offload_kv_to_gpu") is True) or
            (eff.get("hw_kv_offload") is True)
        )
    except Exception:
        kv_user_pref = False

    pending_gb = 0.0
    try:
        pending_gb = float((user_kwargs or {}).get("_pending_gb") or 0.0)
    except Exception:
        pending_gb = 0.0

    # first pass (before fallback)
    live_free_gb = max(free_gb - max(pending_gb, 0.0), 0.0)

    # if projection probe didn’t give us a reasonable free/total, fall back and then recompute live headroom
    if total_gb <= 0.0 or free_gb < 0.01:
        try:
            fb = _gpu_free_bytes()
            if fb > 0:
                free_gb = fb / (1024**3)
                if total_gb <= 0.0:
                    total_gb = max(proj_gb + 0.1, 1.0)
                log.info("[guardrail.fallback] using direct GPU free=%.2fGB total~%.2fGB", free_gb, total_gb)
            else:
                log.warning("[guardrail.fallback] NVML/nvidia-smi unavailable; proceeding conservatively")
        except Exception as _e:
            log.warning("[guardrail.fallback] error probing GPU free: %r", _e)

        # >>> IMPORTANT: recompute live_free_gb after we updated free_gb <<<
        live_free_gb = max(free_gb - max(pending_gb, 0.0), 0.0)

    def _budget_for(_mode: str) -> float:
        vmm_headroom = 0.10 if (env_patch.get("GGML_CUDA_NO_VMM") == "1") else 0.00

        if _mode == "off":
            return float("+inf")

        if _mode == "strict":
            return min(
                max(live_free_gb - (0.25 + vmm_headroom), 0.0),
                (0.85 - vmm_headroom) * total_gb,
            )

        if _mode == "balanced":
            return min(
                max(live_free_gb - (0.15 + vmm_headroom), 0.0),
                (0.93 - vmm_headroom) * total_gb,
            )

        if _mode == "relaxed":
            return min(
                max(live_free_gb - (0.05 + vmm_headroom), 0.0),
                (0.99 - vmm_headroom) * total_gb,
            )

        if _mode == "custom" and isinstance(custom_gb, (int, float)):
            # Treat custom GB as an upper bound, but never exceed live headroom
            cap = min(
                max(live_free_gb - (0.15 + vmm_headroom), 0.0),
                (0.93 - vmm_headroom) * total_gb,
            )
            return max(min(float(custom_gb), cap), 0.0)

        # default similar to balanced
        return min(
            max(live_free_gb - (0.15 + vmm_headroom), 0.0),
            (0.93 - vmm_headroom) * total_gb,
    )

    budget_gb = _budget_for(mode)

    # optional auto-fit of n_gpu_layers when user didn't pin it
    if auto_fit and (not isinstance(ngl_in, int) or ngl_in <= 0):
        target_model_gb = max(0.0, budget_gb - (kv_gb + 0.2))
        ngl_auto = int(max(1, min(total_layers, (target_model_gb / per_layer_gb) if per_layer_gb > 0 else 1)))
        cleaned["n_gpu_layers"] = ngl_auto
        ngl_eff = ngl_auto
        model_gb = per_layer_gb * ngl_eff
        proj_gb = model_gb + kv_gb + 0.2
        log.info(
            "[guardrail.auto-ngl] mode=%s per_layer≈%.2fGB budget≈%.2fGB -> n_gpu_layers=%d (model_gb≈%.2fGB proj≈%.2fGB)",
            mode, per_layer_gb, budget_gb, ngl_auto, model_gb, proj_gb
        )

    # If user pinned layers and we exceed budget, bounce (abort) without mutating layers
    # If we're over budget and the adjustments we'd need are hard-pinned, abort now.
    if proj_gb > budget_gb:
        # Which moves are theoretically available?
        want_flip_kv = kv_on and not kv_user_pref
        can_flip_kv  = want_flip_kv and (not user_set_kv_hard)

        want_drop_layers = (per_layer_gb > 0 and isinstance(ngl_eff, int) and ngl_eff > 1)
        can_drop_layers  = want_drop_layers and (not user_set_layers_hard)

        want_shrink_ctx = kv_on and n_ctx > 2048
        can_shrink_ctx  = want_shrink_ctx and (not user_set_ctx_hard)

        if not (can_flip_kv or can_drop_layers or can_shrink_ctx):
            # Nothing we’re allowed to touch — bounce.
            diag = {
                "mode": mode,
                "projGB": round(proj_gb, 2),
                "freeGB": round(free_gb, 2),
                "freeGBLive": round(live_free_gb, 2),
                "pendingGB": round(pending_gb, 2),
                "totalGB": round(total_gb, 2),
                "budgetGB": None if budget_gb == float("inf") else round(budget_gb, 2),
                "kvOn": bool(kv_on),
                "nGpuLayers": cleaned.get("n_gpu_layers"),
                "nCtx": int(cleaned.get("n_ctx", n_ctx)),
                "autoFit": bool(auto_fit),
                "strictPreferCpuKV": bool(strict_prefer_cpu_kv),
                "steps": 0,
                "decision": "abort_over_budget_hard_pins",
                "pins": {
                    "kvOffload": user_set_kv_hard,
                    "layers": user_set_layers_hard,
                    "ctx": user_set_ctx_hard,
                },
                "suggested": {
                    "layersThatFit": (
                        max(1, int((max(0.0, budget_gb - (kv_gb + 0.2))) / per_layer_gb))
                        if per_layer_gb > 0 else 1
                    ),
                },
            }
            return cleaned, env_patch, diag

    # ---------- bounded-spillover loop (single pass, deterministic) ----------
    # keep adjusting until we are ≤ budget or we run out of knobs
    kv_user_pref = False
    try:
        kv_user_pref = bool(
            (eff.get("gpu_offload_kv") is True) or
            (wd.get("offload_kv_to_gpu") is True) or
            (eff.get("hw_kv_offload") is True)
        )
    except Exception:
        pass

    max_steps = 6
    steps = 0
    while proj_gb > budget_gb and steps < max_steps:
        steps += 1

        # 1) KV → CPU (unless user pinned KV)
        if kv_on and not kv_user_pref and (not user_set_kv_hard):
            cleaned["offload_kqv"] = False
            cleaned["kv_offload"] = False
            kv_on = False
            kv_gb = 0.0
            proj_gb = model_gb + kv_gb + 0.2
            log.info("[guardrail.fit] step=%d → KV→CPU; proj≈%.2fGB budget≈%.2fGB", steps, proj_gb, budget_gb)
            continue

        # 2) Drop layers (unless user pinned layers)
        need_gb = max(0.0, proj_gb - budget_gb)
        if (not user_set_layers_hard) and per_layer_gb > 0 and isinstance(ngl_eff, int) and ngl_eff > 1 and need_gb > 0:
            drop = int(max(1, (need_gb // per_layer_gb) + (1 if (need_gb % per_layer_gb) > 1e-6 else 0)))
            new_ngl = max(1, ngl_eff - drop)
            if new_ngl != ngl_eff:
                ngl_eff = new_ngl
                cleaned["n_gpu_layers"] = ngl_eff
                model_gb = per_layer_gb * ngl_eff
                proj_gb = model_gb + kv_gb + 0.2
                log.info("[guardrail.fit] step=%d → layers=%d; proj≈%.2fGB budget≈%.2fGB", steps, ngl_eff, proj_gb, budget_gb)
                continue

        # 3) Shrink context (only if KV still on GPU, not pinned, and > 2048)
        if kv_on and n_ctx > 2048 and (not user_set_ctx_hard):
            new_ctx = max(2048, int(n_ctx * 0.85))
            if new_ctx != n_ctx:
                n_ctx = new_ctx
                cleaned["n_ctx"] = n_ctx
                kv_gb = _kv_gb(n_ctx, kv_on)
                proj_gb = model_gb + kv_gb + 0.2
                log.info("[guardrail.fit] step=%d → n_ctx=%d; proj≈%.2fGB budget≈%.2fGB", steps, n_ctx, proj_gb, budget_gb)
                continue

        # nothing else to adjust
        break

    # ------------------------------------------------------------------------

    # Be conservative with VMM when running under strict/custom budgets
    if mode in {"strict", "custom"}:
        env_patch["GGML_CUDA_NO_VMM"] = "1"

    # final projection log
    log.info(
        "[guardrail.proj] model=%.2fGB kv=%.2fGB ovh=0.20GB -> proj=%.2fGB free=%.2fGB total=%.2fGB mode=%s kv_on=%s ngl=%s n_ctx=%s",
        model_gb, kv_gb, model_gb + kv_gb + 0.2, free_gb, total_gb, mode, kv_on, cleaned.get("n_gpu_layers"), cleaned.get("n_ctx", n_ctx)
    )

    # sanitize n_gpu_layers on GPU path
    if cleaned.get("n_gpu_layers") is not None:
        try:
            ngl = int(cleaned["n_gpu_layers"])
            if ngl <= 0:
                cleaned["n_gpu_layers"] = 1
                log.info("[spawn.sanitize] corrected n_gpu_layers 0 -> 1 (GPU path safe floor)")
        except Exception:
            pass

    # diag payload
    budget_preview = None if budget_gb == float("inf") else round(budget_gb, 2)
    diag = {
        "mode": mode,
        "projGB": round(model_gb + kv_gb + 0.2, 2),
        "freeGB": round(free_gb, 2),
        "freeGBLive": round(live_free_gb, 2),
        "pendingGB": round(pending_gb, 2),
        "totalGB": round(total_gb, 2),
        "budgetGB": budget_preview,
        "kvOn": bool(kv_on),
        "nGpuLayers": cleaned.get("n_gpu_layers"),
        "nCtx": int(cleaned.get("n_ctx", n_ctx)),
        "autoFit": bool(auto_fit),
        "strictPreferCpuKV": bool(strict_prefer_cpu_kv),
        "steps": steps,
    }

    return cleaned, env_patch, diag
