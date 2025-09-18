from llama_cpp import Llama

hits = 0
def cb(progress, *_a, **_kw):
    global hits
    hits += 1
    print("progress_cb", progress)
    return True

llm = Llama(model_path="C:/Users/joshb/AppData/Roaming/LocalAI/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
            progress_callback=cb,
            n_ctx=4096)
print("callback hits:", hits)
