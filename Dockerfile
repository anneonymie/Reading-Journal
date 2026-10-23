# Debian 13 ("trixie") ships SQLite 3.46; the default Debian 12 image's 3.40 is too old for the schema.
FROM python:3.13-slim-trixie

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY schema.sql run.py ./
COPY journal ./journal

# Your data lives outside the container, in a folder mounted here.
ENV JOURNAL_DATA=/data \
    JOURNAL_HOST=0.0.0.0 \
    JOURNAL_PORT=8420 \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8420

# Fails the build early if this image's SQLite is ever too old.
RUN python -c "from journal.db import check_sqlite; check_sqlite()"

CMD ["python", "run.py"]
