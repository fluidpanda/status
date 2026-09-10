FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > requirements.txt \
    && pip install --no-cache-dir -r requirements.txt
CMD ["python", "-m", "uvicorn", "status.app:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "75"]
