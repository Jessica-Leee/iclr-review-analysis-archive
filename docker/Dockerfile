FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN rm -rf data/raw .venv __pycache__ .git 2>/dev/null || true
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "run.py"]
