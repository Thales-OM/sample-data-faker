ARG PYTHON_VERSION=3.11

FROM docker-hub-proxy.wildberries.ru/library/python:${PYTHON_VERSION}-slim

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

EXPOSE 8080

ENTRYPOINT ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
