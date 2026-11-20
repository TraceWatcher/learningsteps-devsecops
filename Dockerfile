
FROM python:3.12-alpine

WORKDIR /app

# Application version supplied during the release build
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

# Apply available Alpine security updates
RUN apk upgrade --no-cache

# Install Python dependencies
COPY api/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Create unprivileged user
RUN addgroup -S appgroup \
    && adduser -S -D -H -G appgroup appuser

COPY --chown=appuser:appgroup api/ /app/

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
