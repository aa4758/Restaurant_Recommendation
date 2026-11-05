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
    limit: int = Field(default=3, ge=1, le=20)  # 한 번에 받을 개수(2026-11-02: 목록 이어 보기, 최대 20)
    offset: int = Field(default=0, ge=0, le=5000)  # 이어 받기 시작 위치
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
    relaxed: list[Literal["mood", "price", "subtype", "distance", "genre"]] = []  # 이 가게가 원래 조건 중 충족 못한 항목
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
    total: int = 0  # 조건(완화 후)에 맞는 전체 가게 수 — offset+len(items) < total 이면 더 있음


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
    designations: list[str] = []  # 지정목록 표시명(모범음식점·안심식당·원산지표시 우수·백년가게), 표시용


DeviceId = Annotated[str, Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class MenuIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    price: Optional[int] = Field(default=None, ge=1000, le=300_000)

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("blank menu name")
        return v


class Position(BaseModel):
    """현장 작성 판정용(docs/01 R-2). 저장하지 않음."""
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy: Optional[float] = Field(default=None, ge=0)


class ReviewIn(BaseModel):
    stars: float = Field(ge=0.5, le=5)
    text: str = Field(default="", max_length=1000)
    tags: list[Annotated[str, Field(max_length=20)]] = Field(default=[], max_length=10)
    device_id: Optional[DeviceId] = None  # 무시(하위 호환). 작성자는 로그인 계정(app/auth.py)
    spend: Optional[Literal["~1만", "1~2만", "2~4만", "4만+"]] = None  # constants.PRICE_BANDS (R-5)
    moods: list[Literal["조용한", "회식", "데이트", "혼밥", "가성비", "노포"]] = Field(default=[], max_length=6)  # MOODS (R-6)
    menus: list[MenuIn] = Field(default=[], max_length=3)  # R-4
    positions: list[Position] = Field(default=[], max_length=2)  # 쓰기 화면 열 때·등록할 때

    @field_validator("stars")
    @classmethod
    def half_step(cls, v: float) -> float:
        if abs(v * 2 - round(v * 2)) > 1e-9:
            raise ValueError("stars must be in 0.5 steps")
        return v


class ReviewOut(BaseModel):
    id: int
    final_star: float
    updated: bool = False  # 기존 리뷰를 덮어씀
    onsite: bool = False


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
    onsite: bool = False
    edited: bool = False


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
