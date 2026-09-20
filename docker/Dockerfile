FROM python:3.11-slim

WORKDIR /app

# weasyprint 依赖（PDF 渲染）+ 中文字体（2026-08-15）
# libxcb/glib 等 = onnxruntime/OpenCV 运行库（2026-08-18 图片 OCR 用）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev \
        fonts-noto-cjk \
        libxcb1 libxcb-shm0 libxcb-xfixes0 libxcb-render0 libxcb-shape0 \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt

COPY apps/api ./apps/api
COPY services ./services
COPY adapters ./adapters

# 数据卷（2026-08-07 数据库化）：geo.db + 媒体文件统一挂载
# 宿主机挂载示例：-v $(pwd)/geo_storage:/app/geo_storage
# geo.db 默认位于 /app/geo.db（GEO_DB_PATH 可覆盖），媒体默认 /app/storage/media（GEO_MEDIA_DIR 可覆盖）
ENV GEO_DB_PATH=/app/geo_storage/geo.db \
    GEO_MEDIA_DIR=/app/geo_storage/media

WORKDIR /app/apps/api
EXPOSE 3002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3002"]
