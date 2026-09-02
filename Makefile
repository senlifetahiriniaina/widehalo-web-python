.PHONY: up down build migrate test lint format typecheck shell logs css-build css-watch

up:
	docker compose up

build:
	docker compose build

down:
	docker compose down

migrate:
	docker compose exec web python manage.py migrate

makemigrations:
	docker compose exec web python manage.py makemigrations

makemessages:
	docker compose exec web python manage.py makemessages -l fr -l en --no-location

compilemessages:
	docker compose exec web python manage.py compilemessages

test:
	docker compose exec web pytest

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy widehalo

shell:
	docker compose exec web python manage.py shell

logs:
	docker compose logs -f

# Socle Tailwind/DaisyUI de la refonte UX (Sprint 0, cf.
# docs/planning/2026-refonte-ux-sprints.md). Tourne sur l'hote (npm), pas
# dans le conteneur web (image Python sans Node) -- a lancer avant `make
# build`/commit si static/css/tailwind-input.css ou templates/cotton/
# changent. Le CSS compile (static/css/tailwind.css) est commite.
css-build:
	npm run build:css

css-watch:
	npm run watch:css
