FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir .

ENV SCHOLAR_HOME=/data
RUN mkdir -p /data

EXPOSE 8000

ENTRYPOINT ["scholar-agent"]
CMD ["serve-mcp"]
