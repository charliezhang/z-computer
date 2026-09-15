install:
	cd backend && uv sync
	cd frontend && npm install

dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && uv run uvicorn app.main:app --reload --port 8000) & \
	(cd frontend && npm run dev) & \
	wait

db-reset:
	rm -rf backend/data

.PHONY: install dev db-reset
