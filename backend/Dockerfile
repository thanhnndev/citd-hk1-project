FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (leveraging Docker layer caching)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY backend/app/ ./app/

# Copy agents package (LangGraph multi-agent orchestration)
COPY agents/ ./agents/

# Expose port
EXPOSE 8000

# Run the ASGI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
