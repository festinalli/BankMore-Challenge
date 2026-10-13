# BankMore ML Service — treina a v1 no build, serve com Gunicorn.
# A imagem sai com o registro de modelos em /app/artifacts/registro (v1 em produção).
# Retreino, sombra, portão e reversão rodam no container (ver ml/README.md, ADR 0023):
#   docker exec bankmore-fraud-ml python retreinar.py --versao xgboost-v2 --cenario base+nova_fraude

FROM python:3.11-slim AS base

WORKDIR /app

# Dependências do sistema (xgboost precisa de libgomp1)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Treina o modelo durante o BUILD da imagem. Determinístico (seed fixo).
# Resultado: registro em /app/artifacts/registro com a v1 em produção, mais os
# antigos /app/artifacts/{model.joblib, metrics.json}.
COPY dados.py drift.py registro.py retreinar.py portao.py train.py criterio_promocao.json ./
RUN python train.py

# Servidor Flask
COPY app.py .

EXPOSE 5003
ENV PORT=5003
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=10s --timeout=3s --retries=5 --start-period=5s \
    CMD curl -fsS http://localhost:5003/health || exit 1

# Gunicorn com 1 processo e 4 threads: contadores Prometheus, janela de drift e
# estado da sombra ficam num processo só (com 2 workers sync, cada scrape via um
# worker e os alertas sobre contadores ficavam errados). O predict do XGBoost
# (booster de árvores) é thread-safe.
CMD ["gunicorn", "-b", "0.0.0.0:5003", "-w", "1", "-k", "gthread", "--threads", "4", "--timeout", "30", "app:app"]
