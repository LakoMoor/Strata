# CUDA 12 is required for V100 / sm70. Models and signed release runtime are mounted, never copied.
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgomp1 libnuma1 libatomic1 zlib1g \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/dashboard
COPY server.py /opt/dashboard/server.py
COPY web/ /opt/dashboard/web/
ENV NVIDIA_VISIBLE_DEVICES=0 NVIDIA_DRIVER_CAPABILITIES=compute,utility PYTHONUNBUFFERED=1
EXPOSE 8000
ENTRYPOINT ["/workspace/strata-v100/runtime/terminal/0.1.55/python/bin/python3.12", "/opt/dashboard/server.py"]
CMD ["--config", "/workspace/strata-v100/dashboard-state/engine.json", "--python", "/workspace/strata-v100/runtime/terminal/0.1.55/python/bin/python3.12", "--host", "0.0.0.0", "--port", "8000"]
