.PHONY: help run docker_build docker_run compose_up

help:
	@echo "Available commands:"
	@echo "  run            Run locally using Python"
	@echo "  docker_build   Build Docker image"
	@echo "  docker_run     Run Docker container"
	@echo "  compose_up     Build and run multicontainer compose with nginx as load-balancer"

run:
	python main.py

docker_build:
	docker build -t sample-data-faker -f deploy/services/sample-data-faker/Dockerfile .

docker_run:
	docker run -p 8000:8000 sample-data-faker

compose_up:
	docker-compose -f deploy/docker-compose.yml up --build --scale worker=2 -d
