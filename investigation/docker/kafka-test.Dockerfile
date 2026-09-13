# Isolated integration broker; not a production Kafka deployment.
# Archive and SHA-512 are published by Apache for Kafka 3.9.1.
FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-21-jre-headless curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/kafka
RUN curl --fail --retry 3 -o /tmp/kafka.tgz https://archive.apache.org/dist/kafka/3.9.1/kafka_2.13-3.9.1.tgz \
    && echo '1ea204ba73411737a275429ca976d440f007ff0957b90b19be41dc5a4bae52617267769be9f0b5791714d0b3c4c760605bd426faea39edd90763585523fa2cfe  /tmp/kafka.tgz' | sha512sum -c - \
    && tar -xzf /tmp/kafka.tgz --strip-components=1 \
    && rm /tmp/kafka.tgz \
    && useradd --create-home kafka \
    && mkdir /tmp/kraft-logs && chown -R kafka:kafka /opt/kafka /tmp/kraft-logs
COPY kafka-test.properties /opt/kafka/config/test.properties
USER kafka
ENV KAFKA_HEAP_OPTS="-Xms256m -Xmx512m"
CMD ["sh", "-c", "bin/kafka-storage.sh format --ignore-formatted -t MkU3OEVBNTcwNTJENDM2Qk -c config/test.properties && exec bin/kafka-server-start.sh config/test.properties"]
