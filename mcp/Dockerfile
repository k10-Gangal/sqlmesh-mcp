FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
EXPOSE 8090
HEALTHCHECK --interval=5s --timeout=3s --retries=30 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8090/health')"
CMD ["python", "server.py"]
