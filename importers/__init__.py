"""Bulk importers that fill `foods` from external datasets.

Importers never go through the ORM one row at a time — the OpenFoodFacts dump
alone is millions of products. They stream, normalize, `COPY` into an UNLOGGED
staging table and merge with `INSERT ... ON CONFLICT (source, source_id)`.
"""
