FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data/seed ./data/seed
ENV JJINMAT_DB=/data/jjinmat.db
VOLUME /data
EXPOSE 8000
# FORWARDED_ALLOW_IPS: X-Forwarded-For 를 신뢰할 LB/프록시 대역(기본 127.0.0.1 = 직접 연결만). 레이트리밋 IP 키에 사용
# DB가 없을 때만 시드 적재 (load_seed 는 기존 DB를 지우므로 사용자 리뷰 보호)
CMD ["sh", "-c", "[ -f \"$JJINMAT_DB\" ] || python -m app.ingest.load_seed; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
