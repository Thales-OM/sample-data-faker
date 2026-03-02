ARG PYTHON_VERSION=3.11

FROM harbor.wildberries.ru/devops/ci/base-images/python:${PYTHON_VERSION}-slim

# Установка nexus репозитория
ARG NEXUS_PROXY=https://nexus-proxy.wb.ru 


# Установка переменных для python
ENV PIP_INDEX_URL="${NEXUS_PROXY}/repository/pypi-group/simple" \
    PIP_EXTRA_INDEX_URL="${NEXUS_PROXY}/repository/pypi-proxy/simple" \
    PYTHONPYCACHEPREFIX=/tmp/pycache \
    PIP_TRUSTED_HOST=${NEXUS_PROXY} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN pip3 install --upgrade pip

COPY requirements.txt .
RUN pip3 install -r requirements.txt

WORKDIR /app
COPY . .

# Create non-root user and set proper permissions
RUN useradd -m -s /bin/bash appuser && \
    chown -R appuser:appuser /app

# update PATH environment variable (for the new user)
ENV PATH=/home/appuser/.local/bin:$PATH

RUN ln -s /etc/env/.env /app/.env

# run container as non-root user
USER appuser

EXPOSE 8000

CMD [ "python3", "/app/main.py" ]
