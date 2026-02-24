.PHONY: demo dev test seed reset clean

# ─── Docker demo ──────────────────────────────────────────────────
demo:  ## Start the full stack via Docker Compose (server + web + optional ngrok)
	docker compose up --build

demo-tunnel:  ## Start with ngrok tunnel (requires NGROK_AUTHTOKEN)
	docker compose --profile tunnel up --build

# ─── Local development ────────────────────────────────────────────
dev:  ## Start server + web locally (no Docker)
	@echo "Starting server on :3000 and web on :5173..."
	@cd server && uv run uvicorn app.main:app --port 3000 --reload &
	@cd web && npm run dev &
	@wait

dev-server:  ## Start only the backend server
	cd server && uv run uvicorn app.main:app --port 3000 --reload

dev-web:  ## Start only the web frontend
	cd web && npm run dev

dev-ngrok:  ## Start ngrok tunnel to :3000
	ngrok http 3000 --domain=nongraceful-shauna-caritive.ngrok-free.dev

# ─── Testing ──────────────────────────────────────────────────────
test:  ## Run all tests (server + web)
	cd server && uv run python -m pytest -x -q
	cd web && npm test -- --run

test-server:  ## Run server tests only
	cd server && uv run python -m pytest -x -q

test-web:  ## Run web tests only
	cd web && npm test -- --run

# ─── Seed / reset ────────────────────────────────────────────────
seed:  ## Seed demo data into the local database
	cd server && SEED_DEMO=true uv run python -c "from app.seed import seed_demo_data; print(seed_demo_data())"

reset:  ## Wipe all data and re-seed demo environment
	cd server && uv run python -c "from app.seed import wipe_demo_data, seed_demo_data; wipe_demo_data(); print(seed_demo_data())"

# ─── Cleanup ──────────────────────────────────────────────────────
clean:  ## Remove database, caches, and Docker volumes
	rm -f server/callme.db
	find server -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	docker compose down -v 2>/dev/null || true

# ─── Help ─────────────────────────────────────────────────────────
help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
