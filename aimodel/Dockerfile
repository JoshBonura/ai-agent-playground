# Use NVIDIA CUDA runtime so libcudart.so.12 is present
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Python 3.11 + build bits for wheels fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-distutils python3-pip \
    build-essential curl git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    python -m pip install --upgrade pip

WORKDIR /app

# Use your requirements that match Pydantic v2 / FastAPI 0.116.x
COPY file_read/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121 \
    -r /app/requirements.txt

# Copy code + model into expected locations
COPY file_read /app/file_read

# CUDA libs on path; import root at /app
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64:${LD_LIBRARY_PATH} \
    PYTHONPATH=/app \
    LLAMA_LOG_LEVEL=DEBUG

EXPOSE 8001
CMD ["uvicorn","file_read.app:app","--host","0.0.0.0","--port","8001"]
