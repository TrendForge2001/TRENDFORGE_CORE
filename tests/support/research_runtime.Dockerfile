FROM python:3.12.14-slim
ARG TEST_UID=1001
RUN useradd --create-home --uid ${TEST_UID} research
WORKDIR /app
COPY requirements-production.lock /tmp/requirements-production.lock
RUN python -m pip install --no-cache-dir -r /tmp/requirements-production.lock
COPY . /app
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
USER research
