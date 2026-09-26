from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RecommendRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=1000, gt=0, le=20000)
    price: Optional[list[str]] = None
    genre: Optional[list[str]] = None
    mood: Optional[list[str]] = None
    alcohol: Literal["any", "yes", "no"] = "any"
    limit: int = Field(default=3, ge=1, le=5)


class Item(BaseModel):
    id: str
    name: str
    genre: str
    price_band: str
    moods: list[str]
    alcohol: bool
    lat: float
    lng: float
    distance_m: Optional[int] = None
    star: float
    percentile: int
    review_count: int
    gov_visits: int
    gov_source: Optional[str] = None
    reasons: list[str]
    updated_at: str


class RecommendResponse(BaseModel):
    items: list[Item]
    relaxed: list[str]


class ScoreBreakdown(BaseModel):
    prior_star: float
    user_mean: Optional[float]
    n: int
    k: int
    gov_bonus: float
    ad_penalty: float


class RestaurantDetail(Item):
    score_breakdown: ScoreBreakdown


class ReviewIn(BaseModel):
    stars: float = Field(ge=0.5, le=5)
    text: str = Field(default="", max_length=1000)
    tags: list[Annotated[str, Field(max_length=20)]] = Field(default=[], max_length=10)

    @field_validator("stars")
    @classmethod
    def half_step(cls, v: float) -> float:
        if abs(v * 2 - round(v * 2)) > 1e-9:
            raise ValueError("stars must be in 0.5 steps")
        return v


class ReviewOut(BaseModel):
    id: int
    final_star: float


class ReportIn(BaseModel):
    field: str = Field(min_length=1, max_length=50)
    message: str = Field(default="", max_length=1000)
