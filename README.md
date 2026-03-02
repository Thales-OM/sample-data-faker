# sample-data-faker

Сервис для генерации синтетических данных на основе реальных данных из различных источников. Использует библиотеку SDV (Synthetic Data Vault) для создания реалистичных синтетических данных, сохраняющих статистические свойства оригинальных данных.

## Основные возможности

- **Генерация синтетических данных** из различных источников (Trino, Avro OCF, JSON, S3)
- **Интеграция с OpenMetadata** — автоматическое получение схемы таблиц и загрузка сгенерированных данных
- **Асинхронная обработка** — очередь задач с ограничением параллелизма
- **Метрики** — встроенный сбор метрик через Prometheus
- **Готовность к масштабированию** — поддержка балансировки нагрузки и health checks

## Запуск локально

### Требования

- Python 3.10+
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
S3_DESTINATION__BUCKET=dto-sample-data
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
| `/table/generate` | POST | Генерация синтетических данных из указанного источника |
| `/openmetadata/generate/{table_fqn}` | POST | Генерация данных и загрузка в OpenMetadata для указанной таблицы |
| `/openmetadata/webhook` | POST | Webhook для автоматической генерации данных при изменении схемы в OpenMetadata |
| `/avro/ocf` | POST | Генерация данных из Avro OCF файла с загрузкой результата в S3 |

### Параметры запросов

**`/table/generate`** и **`/openmetadata/generate/{table_fqn}`** принимают:

```json
{
  "source": { ... },  // Конфигурация источника данных
  "output_size": 100, // Количество строк для генерации
  "load_limit": 1000  // Максимум строк для обучения модели (опционально)
}
```

**`/avro/ocf`** принимает:

- `file` — Avro OCF файл (.avro)
- `output_size` — максимальное количество записей для генерации (1-10000)
- `load_limit` — максимум записей для загрузки из файла (опционально)

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
