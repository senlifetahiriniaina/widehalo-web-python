.PHONY: up down build migrate test lint format typecheck shell logs

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
