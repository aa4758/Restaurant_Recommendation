"""카카오 로컬 API 어댑터 (스텁). 공식 API 만 사용, 크롤링 아님.

환경변수 KAKAO_REST_KEY 미설정 시 available()=False → 적재 skip.
키가 있으면 카테고리 검색(FD6 음식점)으로 기본 정보만 가져옴(장르/가격/분위기는 수기 보강 필요).
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import date

from .base import Record, SourceAdapter

ENDPOINT = "https://dapi.kakao.com/v2/local/search/category.json"


class KakaoLocalAdapter(SourceAdapter):
    kind = "restaurants"
    name = "kakao_local"

    def __init__(self, lat: float = 37.5663, lng: float = 126.9779, radius_m: int = 1000, pages: int = 1):
        self.key = os.environ.get("KAKAO_REST_KEY", "").strip()
        self.lat, self.lng, self.radius_m, self.pages = lat, lng, radius_m, pages

    def available(self) -> bool:
        return bool(self.key)

    def fetch(self) -> list[Record]:
        if not self.available():
            return []
        out: list[Record] = []
        for page in range(1, self.pages + 1):
            qs = urllib.parse.urlencode(
                {"category_group_code": "FD6", "x": self.lng, "y": self.lat, "radius": self.radius_m, "page": page}
            )
            req = urllib.request.Request(f"{ENDPOINT}?{qs}", headers={"Authorization": f"KakaoAK {self.key}"})
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (공식 API)
                data = json.load(resp)
            for d in data.get("documents", []):
                cat = (d.get("category_name") or "").split(">")
                out.append(
                    {
                        "id": f"K{d['id']}",
                        "name": d.get("place_name", ""),
                        "genre": cat[1].strip() if len(cat) > 1 else "기타",
                        "price_band": "1~2만",  # TODO: 수기/제휴 데이터로 보강
                        "moods": [],
                        "alcohol": False,
                        "lat": float(d["y"]),
                        "lng": float(d["x"]),
                        "address": d.get("road_address_name") or d.get("address_name"),
                        "updated_at": date.today().isoformat(),
                    }
                )
            if data.get("meta", {}).get("is_end", True):
                break
        return out
