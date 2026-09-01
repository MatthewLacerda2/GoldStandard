FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements first so the dependency layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application package.
COPY . .

# Drop root only after the dependencies are installed system-wide.
# Port 8000 is unprivileged, so uvicorn needs nothing beyond this.
RUN useradd --create-home --uid 1001 app && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
