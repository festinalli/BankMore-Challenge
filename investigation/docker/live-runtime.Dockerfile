# Local integration fallback when Docker Hub layers are unavailable.
# Runs the repository's actual detector/scoring code, not a mock implementation.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS base
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip python3-venv python3-dev openjdk-17-jdk-headless redis-server libgomp1 build-essential curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PYTHONUNBUFFERED=1

FROM base AS redis
USER nobody
CMD ["redis-server", "--save", "", "--appendonly", "no", "--dir", "/tmp"]

FROM base AS ml
WORKDIR /app
COPY ml/requirements.txt .
RUN pip install --no-cache-dir --timeout 600 -r requirements.txt
COPY ml/train.py ml/app.py ./
RUN python train.py
CMD ["gunicorn", "-b", "0.0.0.0:5003", "-w", "2", "--timeout", "30", "app:app"]

FROM base AS flink
RUN pip install --no-cache-dir uv==0.12.13 && UV_NATIVE_TLS=true uv python install 3.10.19 --install-dir /opt/python && uv venv --python /opt/python/cpython-3.10.19-linux-x86_64-gnu/bin/python3.10 --seed /opt/flink-venv
ENV PATH="/opt/flink-venv/bin:${PATH}"
RUN pip install --no-cache-dir --timeout 600 --prefer-binary 'apache-flink==1.18.1' 'fastavro==1.9.4' 'requests==2.31.0'
RUN pip install --no-cache-dir setuptools==80.9.0
RUN PYFLINK_LIB=$(python -c 'import pyflink,os; print(os.path.dirname(pyflink.__file__)+"/lib")') && curl -fsSL --retry 3 https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.0.2-1.18/flink-sql-connector-kafka-3.0.2-1.18.jar -o "$PYFLINK_LIB/flink-sql-connector-kafka.jar" && curl -fsSL --retry 3 https://repo.maven.apache.org/maven2/org/apache/flink/flink-metrics-prometheus/1.18.1/flink-metrics-prometheus-1.18.1.jar -o "$PYFLINK_LIB/flink-metrics-prometheus.jar"
COPY pyflink/fraud_detector_job.py /opt/job/fraud_detector_job.py
ENV PYFLINK_CLIENT_EXECUTABLE=/opt/flink-venv/bin/python
ENV PYFLINK_PYTHON=/opt/flink-venv/bin/python
WORKDIR /opt/job
CMD ["python", "-u", "fraud_detector_job.py"]
