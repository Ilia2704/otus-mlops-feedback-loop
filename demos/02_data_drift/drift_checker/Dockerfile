FROM python:3.11-slim
WORKDIR /app
COPY demos/02_data_drift/drift_checker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared /app/shared
COPY data /app/data
COPY demos/02_data_drift/drift_checker/main.py /app/main.py
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
