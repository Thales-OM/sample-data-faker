def openmetadata_to_dto_table(table_fqn: str, trino_catalog: str) -> str:
    service, database, schema, table = table_fqn.split(".")
    schema = schema.replace("-", "_")
    table = table.replace("-", "_")
    return f"{trino_catalog}.{schema}.{table}"
