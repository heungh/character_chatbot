FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY character_chatbot.py character_chatbot_auth.py character_chatbot_memory.py ./
COPY character_chatbot_scraper.py ./
COPY chatbot_config.json ./

# Run as non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcheck || exit 1

CMD ["streamlit", "run", "character_chatbot.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.enableCORS=true", \
     "--server.enableXsrfProtection=true"]
