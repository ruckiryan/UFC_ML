# ── Runtime stage ────────────────────────────────────────────────────────────
# Covers: scraper, data cleaning, model training, prediction scripts
FROM python:3.12-slim AS runtime

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY main.py .

# Create mount-point directories so volumes attach cleanly
RUN mkdir -p data models visuals

# ── Dev / Jupyter stage ───────────────────────────────────────────────────────
# Extends runtime with Excel I/O, JupyterLab, and visualisation libraries
FROM runtime AS dev

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

# notebooks/ is mounted as a volume at runtime — not baked into the image
RUN mkdir -p notebooks

EXPOSE 8888

CMD ["jupyter", "lab", \
     "--ip=0.0.0.0", "--port=8888", \
     "--no-browser", "--allow-root", \
     "--LabApp.token=''"]
