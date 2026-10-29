from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class RecommendRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=1000, gt=0, le=20000)
    price: Optional[list[str]] = None
    genre: Optional[list[str]] = None
    subtype: Optional[list[str]] = None  # 세부 분류(2026-10-29)
    mood: Optional[list[str]] = None
    alcohol: Literal["any", "yes", "no"] = "any"
    limit: int = Field(default=3, ge=1, le=5)
    exclude_ids: list[Annotated[str, Field(max_length=64)]] = Field(default=[], max_length=200)  # 싫어요 숨김


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
    address: Optional[str] = None  # 도로명 우선 (공유 문구·지도 링크용)
    evidence: Optional[Literal["low", "mid", "high"]] = None  # scores.evidence (재계산 전 null)
    relaxed: list[Literal["subtype", "distance", "mood", "price", "genre"]] = []  # 이 가게가 원래 조건 중 충족 못한 항목
    subtype: Optional[str] = None  # 세부 분류(미분류 null)


class ParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class ParsedFilters(BaseModel):
    price: list[str] = []
    genre: list[str] = []
    subtype: list[str] = []
    mood: list[str] = []
    alcohol: Literal["any", "yes", "no"] = "any"
    radius_m: Optional[int] = None


class ParseOut(BaseModel):
    filters: ParsedFilters
    unknown: list[str]


class RecommendResponse(BaseModel):
    items: list[Item]
    relaxed: list[str]


class ScoreComponents(BaseModel):
    """점수 모델 v2.1 구성요소별 prior_raw 기여분(가중 적용, 감점은 음수). reputation = 외부 평판."""
    tenure: float
    gov: float
    hygiene: float
    designation: float
    reputation: float
    sanction: float
    ad: float


class ScoreBreakdown(BaseModel):
    prior_star: float
    user_mean: Optional[float]
    n: int
    k: int
    gov_bonus: float
    ad_penalty: float
    components: Optional[ScoreComponents] = None  # NULL(재계산 전) → null
    evidence: Optional[Literal["low", "mid", "high"]] = None


class RestaurantDetail(Item):
    score_breakdown: ScoreBreakdown


DeviceId = Annotated[str, Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class ReviewIn(BaseModel):
    stars: float = Field(ge=0.5, le=5)
    text: str = Field(default="", max_length=1000)
    tags: list[Annotated[str, Field(max_length=20)]] = Field(default=[], max_length=10)
    device_id: Optional[DeviceId] = None  # 레이트리밋·D6용, user_reviews.user_id 에 저장(응답 비노출)

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


class ReviewItem(BaseModel):
    id: int
    stars: float
    text: str
    tags: list[str]
    created_at: str
    ad_disclosed: bool


class ReviewPage(BaseModel):
    items: list[ReviewItem]
    next_cursor: Optional[str] = None


class ReactionIn(BaseModel):
    """기기·가게당 1행. 공개 점수·순위에 반영하지 않음(개인화 전용)."""
    device_id: DeviceId
    restaurant_id: str = Field(min_length=1, max_length=64)
    value: Literal["like", "dislike", "none"]
    reason: Optional[Literal["far", "price", "not_into", "visited"]] = None

    @model_validator(mode="after")
    def reason_only_for_dislike(self) -> "ReactionIn":
        if self.reason is not None and self.value != "dislike":
            raise ValueError("reason is only allowed when value is dislike")
        return self
