{\rtf1\ansi\ansicpg1252\cocoartf2907
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 # CI Pipeline\
\
The CI pipeline is defined in .github/workflows/ci.yml. It runs on every push and PR.\
\
## Jobs\
\
### unit - Fast unit tests (mocked)\
\
Runs first. Mocks OCR / OpenCV / PaddleOCR.\
\
Tests:\
- submissions.tests.test_emailing\
- submissions.tests.test_submissions\
- submissions.tests.test_verification\
\
### integration - Slow OCR / OpenCV tests\
\
Runs only after unit passes. Downloads PaddleOCR models on first run (cached after).\
\
Tests:\
- submissions.tests.test_recognition_document\
- submissions.tests.test_recognition_matching\
- submissions.tests.test_recognition_service\
- submissions.tests.test_student_number_localization\
\
## Model / runtime setup\
\
The integration job requires Python 3.12, paddleocr==3.7.0, paddlepaddle==3.3.1, opencv-contrib-python, opencv-python-headless, and PaddleOCR models (~140 MB at ~/.paddlex).\
\
Models are cached under the key paddlex-models-v1. Bump the key if the model version changes.\
\
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True skips the connectivity check on every run.\
\
## Running locally\
\
Fast unit tests: python manage.py test submissions.tests.test_emailing submissions.tests.test_submissions submissions.tests.test_verification\
\
OCR integration tests: PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True python manage.py test submissions.tests.test_recognition_document submissions.tests.test_recognition_matching submissions.tests.test_recognition_service submissions.tests.test_student_number_localization\
\
## Rules\
\
- CI must be green to merge.\
- If you change a model, run python manage.py makemigrations and commit the file.\
- New tests that mock OCR go in the unit job.\
- New tests that use real image processing go in the integration job.}