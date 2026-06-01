# BankMore fraud-detector — Sprint 2
# Python state machine que implementa a topologia que o PyFlink job teria.
# Sprint 4 troca pelo PyFlink real submetido ao JM/TM (mesmo schema de eventos).
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fraud_detector.py .

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-u", "fraud_detector.py"]
