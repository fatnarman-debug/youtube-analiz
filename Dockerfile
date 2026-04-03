FROM python:3.11-slim

# v1.0.8 - Force rebuild
ARG BUILD_DATE=unknown
ENV APP_VERSION=v1.0.8

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create storage directory with full permissions
RUN mkdir -p /app/storage && chmod 777 /app/storage

# Copy ALL project files (this layer changes with every code update)
COPY . .

# Print version info at build time
RUN echo "VidInsight v1.0.8 built successfully" && python -c "print('Python OK')"

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
