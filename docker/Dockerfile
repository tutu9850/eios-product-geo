FROM node:22-bookworm-slim AS ui
WORKDIR /src
COPY package.json package-lock.json tsconfig.base.json ./
COPY packages/geo/package.json ./packages/geo/
COPY packages/ui/package.json ./packages/ui/
RUN npm ci --no-audit --no-fund
COPY packages/geo ./packages/geo
COPY packages/ui ./packages/ui
RUN npm run build:ui
# Development validation only: contains GEO source; never canonical.
FROM python:3.12-slim-bookworm AS runtime
WORKDIR /opt/eios-product-geo/py
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev fonts-noto-cjk libxcb1 libxcb-shm0 libxcb-xfixes0 libxcb-render0 libxcb-shape0 libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 && rm -rf /var/lib/apt/lists/*
COPY docker/requirements.lock /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && pip check
# Foundation is a named, explicitly supplied build context, not a copied Authority.
COPY --from=foundation packages/contracts/generated/python /tmp/eios-contracts
COPY --from=foundation packages/auth /tmp/eios-auth
COPY --from=foundation packages/policy /tmp/eios-policy
RUN pip install --no-cache-dir /tmp/eios-contracts /tmp/eios-auth /tmp/eios-policy && rm -rf /tmp/eios-contracts /tmp/eios-auth /tmp/eios-policy
COPY apps/api/app ./apps/api/app
COPY services ./services
COPY adapters ./adapters
COPY docker/serve.py ./serve.py
COPY --from=ui /src/packages/geo/dist /opt/eios-geo-ui
ENV GEO_UI_DIR=/opt/eios-geo-ui
ENV PYTHONPATH=/opt/eios-product-geo/py:/opt/eios-product-geo/py/apps/api PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GEO_DB_PATH=/var/lib/eios/geo/geo.db GEO_MEDIA_DIR=/var/lib/eios/geo/media
RUN mkdir -p /var/lib/eios/geo/media /opt/eios-product-geo/py/apps/data && python -c "import app.main; import eios_auth, eios_policy"
EXPOSE 8091
CMD ["python", "/opt/eios-product-geo/py/serve.py"]
