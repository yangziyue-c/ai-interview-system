"""岗位相关 schema"""
from pydantic import BaseModel, ConfigDict


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    description: str
    tech_stack: list[str]
    focus: list[str]
