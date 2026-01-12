FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && \
    apt-get install -y git bash ripgrep fd-find && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
RUN ln -s $(which fdfind) /usr/bin/fd
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
RUN chmod +x *.sh
CMD ["python", "script.py"]