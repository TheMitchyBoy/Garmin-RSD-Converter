FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV SONAR_HOST=0.0.0.0
ENV SONAR_PORT=8080
ENV SONAR_DATA_DIR=/data

VOLUME ["/data"]
EXPOSE 8080

CMD ["python", "sonar_cli.py", "serve", "--host", "0.0.0.0", "--port", "8080", "--data-dir", "/data"]
