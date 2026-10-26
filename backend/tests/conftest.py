import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """메모리 레이트리밋은 프로세스 전역 → 테스트 간 누적 방지."""
    from app.ratelimit import write_limiter
    write_limiter.reset()
    yield
    write_limiter.reset()
