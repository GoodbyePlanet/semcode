QDRANT_URL      := http://localhost:6333
SEMCODE_URL     := http://localhost:8090

.PHONY: qdrant-clean qdrant-dashboard index-code index-history \
        docker-build-restart docker-up docker-logs docker-logs-semcode

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

docker-build-restart:
	docker compose down && docker compose up --build -d

docker-up:
	docker compose up -d

docker-logs:
	docker compose logs -f

docker-logs-semcode:
	docker compose logs -f semcode
