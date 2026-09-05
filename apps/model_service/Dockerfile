FROM python:3.11-slim
WORKDIR /app
COPY apps/model_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared /app/shared
COPY data /app/data
COPY apps/model_service/main.py /app/main.py
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
