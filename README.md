# sample-data-faker

Сервис для генерации синтетических данных на основе реальных данных из различных источников. Использует библиотеку SDV (Synthetic Data Vault) для создания реалистичных синтетических данных, сохраняющих статистические свойства оригинальных данных.

## Основные возможности

- **Генерация синтетических данных** из различных источников (Trino, Avro OCF, JSON, S3)
- **Интеграция с OpenMetadata** — автоматическое получение схемы таблиц и загрузка сгенерированных данных
- **Асинхронная обработка** — очередь задач с ограничением параллелизма
- **Метрики** — встроенный сбор метрик через Prometheus
- **Готовность к масштабированию** — поддержка балансировки нагрузки и health checks

## Документация и создание собственного пайплайна

См. [docs/pipeline_components.md](./docs/pipeline_components.md)

## Запуск локально

### Требования

- Python 3.11+
- Docker (опционально, для запуска в контейнере)

### Установка зависимостей

```bash
pip install -r requirements.txt
```

### Настройка переменных окружения

Скопируйте файл `.env.example` в `.env` и заполните необходимыми значениями:

```bash
cp .env.example .env
```

Пример конфигурации:

```env
# OpenMetadata
OPENMETADATA_DESTINATION__API_URL=https://data-catalog-dev.wb.ru/api
OPENMETADATA_DESTINATION__API_VERSION=v1
OPENMETADATA_DESTINATION__TOKEN=<token>

# Trino connection
TRINO_SOURCE__HOST=dto-trino.wildberries.ru
TRINO_SOURCE__PORT=443
TRINO_SOURCE__USER=<username>

# S3-compatible endpoint
S3_DESTINATION__ENDPOINT=http://localhost:9000
S3_DESTINATION__ACCESS_KEY=minioadmin
S3_DESTINATION__SECRET_KEY=minioadmin
S3_DESTINATION__REGION=us-east-1
S3_DESTINATION__BUCKET=dto-synthetic

# Writing Iceberg tables (Hive Metastore + S3 storage)
HMS_S3_DESTINATION__CATALOG_NAME="synthetic"
HMS_S3_DESTINATION__TYPE="hive"
HMS_S3_DESTINATION__URI="thrift://localhost:9083"
HMS_S3_DESTINATION__WAREHOUSE="s3://dto-synthetic/warehouse/"
HMS_S3_DESTINATION__S3_ACCESS_KEY_ID="minioadmin"
HMS_S3_DESTINATION__S3_SECRET_ACCESS_KEY="minioadmin"
HMS_S3_DESTINATION__WRITE_FORMAT_DEFAULT="parquet"
HMS_S3_DESTINATION__S3_REGION="us-east-1"
HMS_S3_DESTINATION__S3_ENDPOINT="http://localhost:9000"

# FastAPI app args
FASTAPI__ROOT_PATH=""

# Worker settings (max concurrency and backpressure)
MAX_THREADS=2
MAX_PENDING=3
```

### Запуск через Python

```bash
make run
# или
python main.py
```

### Запуск в Docker

```bash
# Сборка образа
make docker_build

# Запуск контейнера
make docker_run
```

### Запуск с nginx и балансировщиком нагрузки

```bash
make compose_up
```

Запустит приложение с 2 репликами worker'ов.

## API Endpoints

### Health Checks

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/liveness` | GET | Проверка работоспособности приложения |
| `/readiness` | GET | Проверка готовности обрабатывать запросы (возвращает 503 при максимальной загрузке) |

### Генерация данных

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/v1/table/generate` | POST | Генерация синтетических данных из указанного источника |
| `/api/v1/openmetadata/generate/{table_fqn}` | POST | Генерация данных и загрузка в OpenMetadata для указанной таблицы |
| `/api/v1/openmetadata/webhook` | POST | Webhook для автоматической генерации данных при изменении схемы в OpenMetadata |
| `/api/v1/dto/avro-ocf` | POST | Генерация данных из Avro OCF файла с загрузкой результата в S3 и Iceberg таблицу (Hive Metastore + S3) |

### Параметры запросов

**`/api/v1/table/generate`** и **`/api/v1/openmetadata/generate/{table_fqn}`** принимают:

```json
{
  "source": { ... },  // Конфигурация источника данных
  "output_size": 100, // Количество строк для генерации
  "load_limit": 1000  // Максимум строк для обучения модели (опционально)
}
```

**`/api/v1/dto/avro-ocf`** принимает:

```json
{ 
  "file_content": "T2JqAQAEFGF2cm8uc2NoZW1hHnsidHlwZSI6InJlY29yZCIsIm5hbWUiOiJ0ZXN0IiwiZmllbGRzIjpbeyJuYW1lIjoiaWQiLCJ0eXBlIjoiaW50In1dfRQGYXZyby5jb2RlYwZzbmFwcHkAEPFGNVtbFhwriApCDQ4ODg4ODg4AAAEAMDAwMDAwMDAwMDAwMMA=", // Содержимое Avro OCF (.avro) файла в виде base64 строки
  "filename": "data.avro", // Имя исходного файла, исключительно для логирования и метаданных (название итоговых таблицы / берется из схемы) (опционально)
  "output_size": 100, // Максимальное количество записей для генерации (1-10000)
  "load_limit": 1000// Максимум записей для загрузки из файла (опционально)
}
```

### Источники данных

Сервис поддерживает различные источники данных: Trino, Avro OCF, JSON, S3, Dummy.

Подробное описание структуры источников доступно в:
- [OpenAPI спецификация](http://localhost:8000/openapi.json) запущенного приложения
- Исходный код: [`src/sources/`](src/sources/)

## Kubernetes

При развертывании в Kubernetes приложение поддерживает:

- **Масштабирование** — реплики настраиваются через Helm values для балансировки нагрузки через ingress controller
- **Readiness probe** — проверка готовности по эндпоинту `/readiness` (initialDelaySeconds: 5, periodSeconds: 10)
- **Liveness probe** — проверка работоспособности по эндпоинту `/liveness`
- **Ingress** — маршрутизация через dg-tools ingress controller с аннотацией rewrite-target

Конфигурация ресурсов (CPU/memory) настраивается отдельно для stage и prod окружений.

## Структура проекта

```
sample-data-faker/
├── src/
│   ├── app/            # FastAPI приложение
│   ├── sources/        # Источники данных (Trino, Avro, JSON, S3)
│   ├── destinations/   # Назначения (OpenMetadata, S3)
│   ├── core/           # Основная логика генерации
│   ├── models/         # Pydantic модели
│   └── config/         # Конфигурация
├── deploy/             # Helm charts и конфигурация K8s
├── examples/           # Примеры использования
└── main.py             # Точка входа
```

## Лицензия

Внутренний инструмент dg-tools.
