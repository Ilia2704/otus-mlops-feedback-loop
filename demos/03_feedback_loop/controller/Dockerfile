FROM python:3.11-slim
WORKDIR /app
COPY demos/03_feedback_loop/controller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY demos/03_feedback_loop/controller/main.py /app/main.py
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
