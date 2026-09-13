# Fallback when the pgvector registry image cannot be downloaded.
# Uses the official PostgreSQL image and its configured PGDG package repository.
FROM postgres:16
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
