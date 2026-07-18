# Use official Playwright Python image which has all browser dependencies pre-installed
FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy

# Set working directory
WORKDIR /app

# Copy requirements file first for caching
COPY requirements.txt .

# Install dependencies (since base image already has playwright, we just install Python deps)
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose port the FastAPI app runs on
EXPOSE 8080

# Run the FastAPI app via uvicorn
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8080"]
