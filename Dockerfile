# One image for the API and both workers; the container command decides
# which one runs (see docker-compose.yml and DOCS/DEPLOYMENT.md).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Shared libraries OpenCV and PaddlePaddle load at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Dependencies before the code, so a code change reuses this (large) layer.
COPY requirements.txt .
COPY tools/check_recognition_runtime.py /tmp/check_recognition_runtime.py
RUN pip install -r requirements.txt \
    && pip check \
    && python /tmp/check_recognition_runtime.py

RUN mkdir -p /data/media && chown app:app /data/media

# Bake the OCR models (~140 MB, into /home/app) so a new container doesn't
# download them on its first recognition. Before the code is copied, so a
# code change doesn't download them again. Keep the options in sync with
# get_ocr() in submissions/recognition/localization.py.
USER app
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, enable_mkldnn=False)"
USER root

# Code stays owned by root: the app user can read it but not change it.
# The app only writes to /tmp and the media volume.
COPY . .

# Django admin assets. The key only satisfies settings during the build.
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput

USER app

ENV MEDIA_ROOT=/data/media
EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--config", "config/gunicorn.conf.py"]
