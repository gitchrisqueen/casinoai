FROM python:3

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# For unstructured
RUN apt-get update -y
Run apt-get install -y \
    poppler-utils \
    tesseract-ocr \
    libtesseract-dev

# Download NLTK Data Packagies \
RUN python3 -m nltk.downloader popular #all

COPY . .

#CMD [ "python", "./your-daemon-or-script.py" ]

COPY ./docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
ENTRYPOINT ["/docker-entrypoint.sh"]