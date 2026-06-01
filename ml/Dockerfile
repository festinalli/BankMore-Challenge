# BankMore ML Service — treina no build, serve com Gunicorn.
# Imagem final tem o modelo embutido em /app/artifacts/model.joblib.
# Pra retreinar: docker compose build --no-cache fraud-ml

FROM python:3.11-slim AS base

WORKDIR /app

# Dependências do sistema (xgboost precisa de libgomp1)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Treina o modelo durante o BUILD da imagem. Determinístico (seed fixo).
# Resultado: /app/artifacts/{model.joblib, metrics.json} embutidos.
COPY train.py .
RUN python train.py

# Servidor Flask
COPY app.py .

EXPOSE 5003
ENV PORT=5003
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=10s --timeout=3s --retries=5 --start-period=5s \
    CMD curl -fsS http://localhost:5003/health || exit 1

# Gunicorn pra produção (2 workers, sync — modelo é pequeno e a chamada é leve)
CMD ["gunicorn", "-b", "0.0.0.0:5003", "-w", "2", "-k", "sync", "--timeout", "30", "app:app"]
