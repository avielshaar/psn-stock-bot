FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY psnbot ./psnbot
COPY config.yaml .
ENV TZ=Asia/Jerusalem PYTHONUNBUFFERED=1
CMD ["python", "-m", "psnbot", "run"]
