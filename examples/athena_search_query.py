from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Literal, List, Union


class FilterCondition(BaseModel):
    field: str
    op: Literal["eq", "neq", "gt", "lt", "contains"]
    value: Union[str, int, float]


class FilterGroup(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    and_: Optional[List[FilterCondition]] = Field(None, alias="and")
    or_: Optional[List[FilterCondition]] = Field(None, alias="or")


class OrderBy(BaseModel):
    field: str
    direction: Literal["asc", "desc"]


class SearchQuery(BaseModel):
    entity: Optional[str] = Field(None, pattern="^(team|event|matches)$")
    filter: Optional[FilterGroup] = None
    orderBy: Optional[OrderBy] = None
    selectTop: Optional[int] = None
