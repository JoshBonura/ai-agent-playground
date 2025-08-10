import os
from fastapi import FastAPI
from pydantic import BaseModel
from llama_cpp import Llama

# Build absolute model path so running from root works
BASE_DIR = os.path.dirname(__file__)
MODEL_PATH = os.path.join(BASE_DIR, "models", "mistral-7b-instruct-v0.2.Q4_K_M.gguf")

# Load Mistral model
llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=4096,
    n_threads=6,       # Adjust for your CPU
    n_gpu_layers=1     # If GPU acceleration available
)

# FastAPI app
app = FastAPI()

class Prompt(BaseModel):
    prompt: str

@app.post("/generate")
async def generate_text(data: Prompt):
    # Instruction prompt to keep it conversational & short
    full_prompt = f"""<s>[INST] You are a friendly, conversational AI assistant. 
Keep responses short (max 2 sentences), sound natural, and avoid numbered or bulleted lists.
Respond in plain text without extra formatting.

User: {data.prompt} [/INST]"""

    output = llm(
        full_prompt,
        max_tokens=20,
        temperature=0.7,
        stop=["</s>"]
    )

    return {"response": output["choices"][0]["text"].strip()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("aimodel.main:app", host="0.0.0.0", port=8000, reload=True)
