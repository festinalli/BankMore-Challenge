FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home investigator
COPY bankmore_intelligence ./bankmore_intelligence
COPY knowledge ./knowledge
USER investigator
EXPOSE 5010
CMD ["python", "-m", "bankmore_intelligence", "serve", "--host", "0.0.0.0"]
