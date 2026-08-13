.PHONY: dev-frontend build-frontend build-extension up down api worker smoke

build-frontend:
	cd frontend && npm install && npm run build

build-extension:
	cd extension && npm install && npx @vscode/vsce package --allow-missing-repository --baseContentUrl https://example.com --baseImagesUrl https://example.com

up:
	docker compose up -d --build

down:
	docker compose down

api:
	cd backend && . .venv/bin/activate && set -a && . ../.env && set +a && PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	cd backend && . .venv/bin/activate && set -a && . ../.env && set +a && PYTHONPATH=. celery -A app.celery_app.celery_app worker -l info

dev-frontend:
	cd frontend && npm run dev -- --host 0.0.0.0 --port 5175

smoke:
	NO_PROXY='*' curl --noproxy '*' -s http://127.0.0.1:8000/api/health && echo
	NO_PROXY='*' curl --noproxy '*' -s http://127.0.0.1:8000/api/auth/settings && echo
