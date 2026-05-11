# Sprint 1 only — auto-approver Python
# Sprint 2 substitui por imagem do job PyFlink real
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY auto_approver.py .

ENTRYPOINT ["python", "-u", "auto_approver.py"]
