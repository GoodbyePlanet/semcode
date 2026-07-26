QDRANT_URL      := http://localhost:6333
SEMCODE_URL     := http://localhost:8090
COMPOSE_WITH_CONFIG := -f docker-compose.yaml -f docker-compose.config-yaml.yml

.PHONY: qdrant-clean qdrant-dashboard index-code index-history docker-build \
        docker-build-restart docker-build-restart-jina docker-up docker-up-jina docker-logs docker-logs-semcode \
        docker-build-restart-with-config docker-build-restart-jina-with-config docker-up-with-config docker-up-jina-with-config

qdrant-clean:
	curl -sf -X DELETE $(QDRANT_URL)/collections/code_symbols && \
	curl -sf -X DELETE $(QDRANT_URL)/collections/git_commits
	@echo "Qdrant collections removed."

qdrant-dashboard:
	open $(QDRANT_URL)/dashboard

index-code:
	curl -sf -X POST $(SEMCODE_URL)/reindex \
		-H "Content-Type: application/json" \
		--no-buffer

index-history:
	curl -sf -X POST $(SEMCODE_URL)/reindex-history \
		-H "Content-Type: application/json" \
		--no-buffer

docker-build:
	docker compose build

docker-build-restart:
	docker compose down && docker compose up --build -d

docker-build-restart-jina:
	docker compose --profile jina down && docker compose --profile jina up --build -d

docker-up:
	docker compose up -d

docker-up-jina:
	docker compose --profile jina up -d

# "-with-config" variants also mount config.yaml (see docker-compose.config-yaml.yml),
# for curated/static services alongside — or instead of — ad-hoc registration.
docker-build-restart-with-config:
	docker compose $(COMPOSE_WITH_CONFIG) down && docker compose $(COMPOSE_WITH_CONFIG) up --build -d

docker-build-restart-jina-with-config:
	docker compose $(COMPOSE_WITH_CONFIG) --profile jina down && docker compose $(COMPOSE_WITH_CONFIG) --profile jina up --build -d

docker-up-with-config:
	docker compose $(COMPOSE_WITH_CONFIG) up -d

docker-up-jina-with-config:
	docker compose $(COMPOSE_WITH_CONFIG) --profile jina up -d

docker-logs:
	docker compose logs -f

docker-logs-semcode:
	docker compose logs -f semcode
