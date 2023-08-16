FROM python:3

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# For unstructured
RUN apt-get update -y
Run apt-get install -y \
#    poppler-utils \
    tesseract-ocr \
    libtesseract-dev \
    ffmpeg  \
    libsm6  \
    libxext6

# Download NLTK Data Packagies - Needed for Unstructured \
# RUN python3 -m nltk.downloader popular #all

COPY . .

COPY ./docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
ENTRYPOINT ["/docker-entrypoint.sh"]