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

infra:
	bash deploy/ec2-up.sh

deploy:
	bash deploy/deploy.sh

ssh:
	. deploy/instance.env && ssh ubuntu@$$HOST

logs:
	. deploy/instance.env && ssh ubuntu@$$HOST sudo journalctl -u z-backend -f

.PHONY: install dev db-reset infra deploy ssh logs
