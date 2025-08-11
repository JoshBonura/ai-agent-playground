from llama_cpp import Llama

llm = Llama(
    model_path=r"E:\Projects\ai-agent-playground\models\mistral-7b-instruct-v0.2.Q4_K_M.gguf",
    n_ctx=4096,
    n_threads=8,
    n_gpu_layers=0  # CPU mode
)

def generate_response(prompt: str):
    output = llm(
        prompt,
        max_tokens=200,
        temperature=0.7,
        stop=["</s>"]
    )
    return output["choices"][0]["text"]

if __name__ == "__main__":
    print(generate_response("Hello AI, how are you?"))