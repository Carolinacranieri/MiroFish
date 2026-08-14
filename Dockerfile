FROM python:3.11

# Install Node.js (18+ required) and necessary tools
RUN apt-get update \
  && apt-get install -y --no-install-recommends nodejs npm \
  && rm -rf /var/lib/apt/lists/*

# Copy uv from the official image
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

# Copy dependency manifests first for better Docker layer caching
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/pyproject.toml backend/uv.lock ./backend/

# Install dependencies
RUN npm ci \
  && npm ci --prefix frontend \
  && cd backend && uv sync --frozen

# Copy project source
COPY . .

# Build the Vue frontend for production
RUN npm run build --prefix frontend

# Render exposes a single public HTTP port
EXPOSE 10000

# Run only the production Flask backend; it also serves the built frontend
CMD ["uv", "run", "--directory", "backend", "python", "run.py"]
