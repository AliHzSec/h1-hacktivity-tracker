FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py logger.py ./

VOLUME ["/app/data"]

ENV LOG_FILE=/app/data/log.txt

CMD ["python", "-u", "main.py"]