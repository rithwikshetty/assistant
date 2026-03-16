FROM python:3.12-slim

# System deps for matplotlib, Pillow, etc.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        libfreetype6-dev \
        libjpeg62-turbo-dev \
        libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# Python packages: executor server + data/document libraries
RUN pip install --no-cache-dir \
    fastapi==0.115.* \
    uvicorn[standard]==0.34.* \
    python-multipart==0.0.* \
    pandas==2.2.* \
    openpyxl==3.1.* \
    xlsxwriter==3.2.* \
    python-docx==1.1.* \
    python-pptx==1.0.* \
    matplotlib==3.9.* \
    numpy==2.1.* \
    scipy==1.14.* \
    seaborn==0.13.* \
    pillow==11.*

# Non-root user
RUN useradd -m -s /bin/bash sandbox
USER sandbox
WORKDIR /home/sandbox

COPY --chown=sandbox:sandbox executor_server.py .

EXPOSE 8100
CMD ["uvicorn", "executor_server:app", "--host", "0.0.0.0", "--port", "8100"]
