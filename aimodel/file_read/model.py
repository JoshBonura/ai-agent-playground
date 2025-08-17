from __future__ import annotations
from pathlib import Path
from llama_cpp import Llama

BASE_DIR = Path(__file__).resolve().parent          # .../aimodel/file_read
MODEL_PATH = (BASE_DIR.parent / "models" / "mistral-7b-instruct-v0.2.Q4_K_M.gguf")
#                          ^ go up to .../aimodel

if not MODEL_PATH.exists():
    raise ValueError(f"Model path does not exist: {MODEL_PATH}")

if "LLM_SINGLETON" not in globals():
    LLM_SINGLETON = Llama(
        model_path=str(MODEL_PATH),
        n_ctx=4096,
        n_threads=8,
        n_gpu_layers=40,
        n_batch=256,
    )

llm = LLM_SINGLETON
