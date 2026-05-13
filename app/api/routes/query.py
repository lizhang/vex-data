"""POST /query/create-tables and POST /query/execute."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from app.config import settings
from app.models.schemas import QueryResponse, SearchQuery
from app.services import athena
from app.services.query_builder import build_query


router = APIRouter()

CURATED_DDL_DIR = Path(__file__).resolve().parents[3] / "curated"


@router.post("/create-tables")
def create_tables():
    tables = athena.create_tables(
        db=settings.athena_database,
        ddl_dir=CURATED_DDL_DIR,
        output_location=settings.athena_output_location,
        workgroup=settings.athena_workgroup,
    )
    return {
        "status": "ok",
        "database": settings.athena_database,
        "tables_created": tables,
    }


@router.post("/execute", response_model=QueryResponse)
def execute(query: SearchQuery) -> QueryResponse:
    sql, params = build_query(query, db=settings.athena_database)
    rows, columns = athena.execute_query(
        sql=sql,
        params=params,
        output_location=settings.athena_output_location,
        workgroup=settings.athena_workgroup,
    )
    return QueryResponse(
        entity=query.entity,
        sql_executed=sql,
        total=len(rows),
        columns=columns,
        rows=rows,
    )
