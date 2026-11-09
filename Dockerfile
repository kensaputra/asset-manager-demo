FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python seed.py --force
EXPOSE 5050
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "2", "app:app"]
