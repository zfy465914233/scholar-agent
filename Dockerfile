FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
COPY schemas/ src/scholar_agent/schemas/
COPY templates/ src/scholar_agent/templates/
COPY config_data/ src/scholar_agent/config_data/
COPY skills/ src/scholar_agent/skills/
COPY validation/ src/scholar_agent/validation/

RUN pip install --no-cache-dir .

ENV SCHOLAR_HOME=/data
RUN mkdir -p /data

EXPOSE 8000

ENTRYPOINT ["scholar-agent"]
CMD ["serve-mcp"]
