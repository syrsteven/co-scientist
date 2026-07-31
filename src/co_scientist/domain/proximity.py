from pydantic import BaseModel, ConfigDict, Field


class ProximityEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    left_id: str
    right_id: str
    similarity: int = Field(ge=1, le=5)
    mechanism_overlap: tuple[str, ...] = ()
    duplicate_likelihood: float = Field(default=0.0, ge=0.0, le=1.0)
