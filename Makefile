.PHONY: help build

help:
	@echo "Available commands:"
	@echo "  build   Build Docker image"

build:
	docker build -t pii-classifier -f docker/Dockerfile .
