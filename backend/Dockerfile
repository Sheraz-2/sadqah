# SadQah backend image: runs the API, payout worker, reconciler and KYC worker
# (docker-compose.yml chooses the command per service).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 sadqah
WORKDIR /srv/backend

COPY pyproject.toml ./
COPY app ./app
RUN pip install .

USER sadqah
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
