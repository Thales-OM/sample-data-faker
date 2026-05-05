# Инструкция

В этом документе объясняется, как импортировать и использовать основные компоненты пайплайна для генерации синтетических данных.

---

## Оглавление

1. [AvroToArrowConverter](#1-avrotoarrowconverter)
2. [SDVPipeline](#2-sdvpipeline)
3. [DataFrameFlattener](#3-dataframeflattener)
4. [Источники данных](#4-источники-данных)
5. [Синтезаторы](#5-синтезаторы)

---

## 1. AvroToArrowConverter

Преобразует записи Apache Avro в PyArrow Table.

### Импорт

```python
from src.sources.avro_ocf import AvroToArrowConverter
```

### Базовое использование

```python
import fastavro
from src.sources.avro_ocf import AvroToArrowConverter

# Загрузка Avro файла
with open("data.avro", "rb") as f:
    reader = fastavro.reader(f)
    avro_schema = reader.writer_schema
    records = list(reader)

# Преобразование в PyArrow Table
converter = AvroToArrowConverter()
table = converter.avro_to_table(
    records=records,      # Список записей Avro
    avro_schema=avro_schema  # Avro схема
)
```

### Методы

| Метод | Описание |
|-------|----------|
| `avro_to_table(records, avro_schema)` | Преобразование записей в PyArrow Table |
| `convert_schema(avro_schema)` | Преобразование Avro схемы (с особенностями схем DTO) в PyArrow схему |
| `records_to_table(records, arrow_schema)` | Создание таблицы из записей со схемой |

---

## 2. SDVPipeline

Полный пайплайн для генерации синтетических данных. Выполняет flatten → fit → sample → unflatten.

### Импорт

```python
from src.core.sdv_pipeline import SDVPipeline
```

### Quick start - Полный пайплайн

```python
from src.core.sdv_pipeline import SDVPipeline
from sdv.single_table import GaussianCopulaSynthesizer
import pyarrow as pa

# Создание или загрузка таблицы
table = pa.Table.from_pydict({
    "id": [1, 2, 3],
    "name": ["Alice", "Bob", "Charlie"],
})

# Запуск полного конвейера
result, metadata, synthesizer = SDVPipeline.run_pipeline(
    synthesizer_cls=GaussianCopulaSynthesizer,  # Класс синтезатора
    data=table,                                # Входной PyArrow Table
    num_rows=100,                              # Строк для генерации
)
```

### Пошаговое использование

```python
from src.core.sdv_pipeline import SDVPipeline
from sdv.single_table import GaussianCopulaSynthesizer
import pyarrow as pa

table = pa.Table.from_pydict({
    "id": [1, 2, 3],
    "value": [10.0, 20.0, 30.0],
})

# Инициализация конвейера
pipeline = SDVPipeline(
    synthesizer_cls=GaussianCopulaSynthesizer,
    model_params={}  # Опциональные параметры
)

# Шаг 1: Выравнивание данных
flat = pipeline.flatten(table)

# Шаг 2: Создание метаданных (опционально, иначе автоматически вызовется в .fit())
metadata = pipeline.create_metadata(flat)

# Шаг 3: Обучение
pipeline.fit(flat)

# Шаг 4: Генерация выборки
synthetic = pipeline.sample(num_rows=10)

# Шаг 5: Восстановление структуры
result = pipeline.unflatten(synthetic)
```

### Доступные синтезаторы

| Синтезатор | Для чего нужен |
|------------|----------------|
| `GaussianCopulaSynthesizer` | Табличные данные с отношениями |
| `CTGANSynthesizer` | Сложные табличные данные, требует GPU |
| `TVAESynthesizer` | Вариационный автоэнкодер |
| `CopulaGANSynthesizer` | Гибрид Copula + GAN |

### Свойства

| Свойство | Описание |
|----------|----------|
| `synthesizer` | Обученный синтезатор (после `fit()`) |
| `metadata` | SDV метаданные (после `fit()`) |

### Результат

Возвращает кортеж `(synthetic_data, metadata, synthesizer)`:
- `synthetic_data` - PyArrow Table с сгенерированными данными
- `metadata` - SDV объект метаданных
- `synthesizer` - Обученный экземпляр синтезатора

---

## 3. DataFrameFlattener

Преобразовывает в плоскую структуру/восстанавливает вложенные PyArrow Table или pandas DataFrame.

### Импорт

```python
from src.core.flatten import DataFrameFlattener
```

### Базовое использование

```python
from src.core.flatten import DataFrameFlattener
import pyarrow as pa

# Создание вложенной таблицы
table = pa.Table.from_pydict({
    "id": [1, 2],
    "user": [
        {"name": "Alice", "age": 30},
        {"name": "Bob", "age": 25},
    ],
})

flattener = DataFrameFlattener()

# Преобразование
flat = flattener.flatten(table)

# Восстановление
restored = flattener.unflatten(flat)
```

### Сохранение схемы развертки

```python
# Сохранение схемы
schema_dict = flattener.schema_to_dict()

# Загрузка схемы позже
flattener = DataFrameFlattener()
flattener.load_schema_from_dict(schema_dict)
```

### Методы

| Метод | Описание |
|-------|----------|
| `flatten(data)` | Выравнивание Table/DataFrame |
| `unflatten(flat_data)` | Восстановление вложенной структуры |
| `schema_to_dict()` | Сериализация схемы |
| `load_schema_from_dict(data)` | Загрузка схемы |

---

## 4. Источники данных

Для примеров Avro, Parquet файлы доступны в директории `examples`.

### Из Apache Avro OCF файла

```python
import fastavro
from src.sources.avro_ocf import AvroToArrowConverter
from src.core.sdv_pipeline import SDVPipeline
from sdv.single_table import GaussianCopulaSynthesizer

# Загрузка
with open("examples/full-covered.avro", "rb") as f:
    reader = fastavro.reader(f)
    avro_schema = reader.writer_schema
    records = list(reader)

# Преобразование
table = AvroToArrowConverter().avro_to_table(
    records=records,
    avro_schema=avro_schema
)

# Конвейер
result, _, _ = SDVPipeline.run_pipeline(
    GaussianCopulaSynthesizer,
    table,
    num_rows=100,
)
```

### Из Parquet файла

```python
from pyarrow.parquet import read_table
from src.core.sdv_pipeline import SDVPipeline
from sdv.single_table import GaussianCopulaSynthesizer

# Загрузка
table = read_table("examples/full-covered.parquet")

# Конвейер
result, _, _ = SDVPipeline.run_pipeline(
    GaussianCopulaSynthesizer,
    table,
    num_rows=100,
)
```

### Из Iceberg таблицы

```python
from pyiceberg.catalog import load_catalog
from src.core.sdv_pipeline import SDVPipeline
from sdv.single_table import GaussianCopulaSynthesizer

# Конфигурация каталога
CATALOG_CONFIG = {
    "name": "synt",
    "type": "hive",
    "uri": "thrift://localhost:9083",
    "warehouse": "s3://bucket/warehouse/",
    "s3.access-key-id": "key",
    "s3.secret-access-key": "secret",
    "py-io-impl": "pyiceberg.io.pyarrow.PyArrowFileIO",
}

# Загрузка каталога и таблицы
catalog = load_catalog(**CATALOG_CONFIG)
table = catalog.load_table("database.table_name").scan().to_arrow()

# Конвейер
result, _, _ = SDVPipeline.run_pipeline(
    GaussianCopulaSynthesizer,
    table,
    num_rows=100,
)
```

---

## Поддерживаемые типы данных

### Вложенные структуры
- `struct` - Вложенные записи
- `list` - Массивы
- `large_list` - Большие массивы

### Примитивы
- `int32`, `int64`, `uint64`
- `float32`, `float64`, `double`
- `string`, `large_string`
- `boolean`
- `decimal`
- `timestamp`
- `date`

### Специальные
- `arrow.uuid` - UUID (хранится как строка)

### Обработка вне диапазона
Временные метки вне диапазона PyArrow (1677-2262) сохраняются как:
```
TIMESTAMP_NS:{epoch_nanoseconds}
```

---

## Частые паттерны

### Пользовательские параметры модели

```python
result, _, _ = SDVPipeline.run_pipeline(
    synthesizer_cls=GaussianCopulaSynthesizer,
    data=table,
    model_params={
        "enforce_min_max_values": True,
        # Другие параметры...
    },
    num_rows=100,
)
```

### Синтезатор на GPU (CTGAN)

```python
result, _, _ = SDVPipeline.run_pipeline(
    synthesizer_cls=CTGANSynthesizer,
    data=table,
    model_params={"cuda": True},  # Требует GPU
    num_rows=100,
)
```

### Сохранение схемы

```python
pipeline = SDVPipeline(synthesizer_cls=GaussianCopulaSynthesizer)
flat = pipeline.flatten(table)
pipeline.fit(flat)

# Генерация
synthetic = pipeline.sample(num_rows=100)

# Восстановление сохраняет оригинальную схему
result = pipeline.unflatten(synthetic)
```

---

## Обработка ошибок

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `ArrowInvalid` | Несоответствие типов при восстановлении | Проверить схему |
| `OutOfBoundsDatetime` | Временная метка вне диапазона | Обрабатывается автоматически |
| `NoSuchTableError` | Таблица Iceberg не найдена | Проверить имя таблицы |
| `NamespaceAlreadyExistsError` | Пространство имен каталога существует | Игнорировать или создать новое |

---
