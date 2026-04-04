FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py
RUN uv pip install --system -e .

COPY . .

EXPOSE 5000

CMD ["gunicorn", "--preload", "--workers", "2", "--bind", "0.0.0.0:5000", "--access-logfile", "-", "--error-logfile", "-", "run:app"]
