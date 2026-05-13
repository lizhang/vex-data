from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ── /query/execute request ─────────────────────────────────────────────────

class FilterCondition(BaseModel):
    field: str
    op: Literal["eq", "neq", "gt", "lt", "contains"]
    value: Union[str, int, float]


class FilterGroup(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    and_: Optional[list[FilterCondition]] = Field(None, alias="and")
    or_: Optional[list[FilterCondition]] = Field(None, alias="or")


class OrderBy(BaseModel):
    field: str
    direction: Literal["asc", "desc"]


class SearchQuery(BaseModel):
    entity: str = Field(..., pattern="^(events|matches|team)$")
    filter: Optional[FilterGroup] = None
    orderBy: Optional[OrderBy] = None
    selectTop: Optional[int] = None


# ── Ingest ─────────────────────────────────────────────────────────────────

class IngestEventsRequest(BaseModel):
    season_id: int
    program_ids: Optional[list[int]] = None


class IngestChildRequest(BaseModel):
    season_id: int
    event_ids: Optional[list[int]] = None


class IngestAllRequest(BaseModel):
    season_id: int
    program_ids: Optional[list[int]] = None


class IngestResult(BaseModel):
    entity: str
    records_fetched: int
    s3_keys: list[str]


# ── Curate ─────────────────────────────────────────────────────────────────

class CurateRequest(BaseModel):
    date: Optional[str] = None


class CurateResult(BaseModel):
    entity: str
    records_written: int
    s3_key: str


# ── Query response ─────────────────────────────────────────────────────────

class QueryResponse(BaseModel):
    entity: str
    sql_executed: str
    total: int
    columns: list[str]
    rows: list[dict]
