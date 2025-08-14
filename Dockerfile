# Usa un'immagine Python ufficiale
FROM python:3.11-slim

# Installa ffmpeg e yt-dlp
RUN apt-get update && apt-get install -y ffmpeg curl && \
    pip install --no-cache-dir yt-dlp && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copia i file dell'app
WORKDIR /app
COPY . /app

# Installa le dipendenze Python
RUN pip install --no-cache-dir -r requirements.txt

# Avvia l'app con uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
