ARG PLATESCOPE_RUNTIME_IMAGE=python:3.12-slim
FROM ${PLATESCOPE_RUNTIME_IMAGE}
USER root
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOST=0.0.0.0 PORT=8000 PLATESCOPE_DATA=/var/lib/platescope
WORKDIR /opt/platescope
COPY requirements.txt scripts/check_dependencies.py ./
RUN (python check_dependencies.py || python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: -r requirements.txt) \
    && python check_dependencies.py && python -m pip check
COPY platescope ./platescope
COPY image_lab ./image_lab
COPY static ./static
COPY templates ./templates
RUN useradd -U -u 11540 platescope && install -d -o platescope -g platescope /var/lib/platescope
USER platescope
EXPOSE 8000
CMD ["python", "-m", "platescope"]
