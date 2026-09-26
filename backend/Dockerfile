FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data/seed ./data/seed
ENV JJINMAT_DB=/data/jjinmat.db
VOLUME /data
EXPOSE 8000
# DB가 없을 때만 시드 적재 (load_seed 는 기존 DB를 지우므로 사용자 리뷰 보호)
CMD ["sh", "-c", "[ -f \"$JJINMAT_DB\" ] || python -m app.ingest.load_seed; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
