.PHONY: help install install-dev deps deps-dev scrape scrape-test clean-data \
        train train-lite predict analysis \
        docker-build docker-scrape docker-scrape-test \
        docker-clean docker-train docker-train-lite docker-predict \
        docker-jupyter docker-down

# ── Default ──────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "UFC ML — available targets"
	@echo ""
	@echo "  Setup"
	@echo "    install         Install core dependencies (requirements.txt)"
	@echo "    install-dev     Install dev dependencies (requirements-dev.txt)"
	@echo "    deps            Recompile requirements.txt from requirements.in"
	@echo "    deps-dev        Recompile requirements-dev.txt from requirements-dev.in"
	@echo ""
	@echo "  Pipeline (local)"
	@echo "    scrape          Scrape all events from ufcstats.com"
	@echo "    scrape-test     Quick scrape test (5 events)"
	@echo "    clean-data      Run data cleaning pipeline"
	@echo "    train           Train full XGBoost model"
	@echo "    train-lite      Train lite XGBoost model (recommended)"
	@echo "    predict         Run unified predictor (requires INPUT=data/<file>.csv)"
	@echo "    analysis        Run feature importance analysis"
	@echo ""
	@echo "  Docker"
	@echo "    docker-build          Build all Docker images"
	@echo "    docker-scrape         Scrape via Docker"
	@echo "    docker-scrape-test    Quick scrape test via Docker"
	@echo "    docker-clean          Clean data via Docker"
	@echo "    docker-train          Train full model via Docker"
	@echo "    docker-train-lite     Train lite model via Docker"
	@echo "    docker-predict        Run predictor via Docker (requires INPUT=data/<file>.csv)"
	@echo "    docker-jupyter        Start JupyterLab on http://localhost:8888"
	@echo "    docker-down           Stop all Docker services"
	@echo "    docker-delete         Stop and remove all Docker services and volumes"
	@echo ""

# ── Setup ────────────────────────────────────────────────────────────────────

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt

deps:
	pip-compile --strip-extras --no-emit-trusted-host --no-header requirements.in -o requirements.txt

deps-dev:
	pip-compile --strip-extras --no-emit-trusted-host --no-header requirements-dev.in -o requirements-dev.txt

# ── Local pipeline ────────────────────────────────────────────────────────────

scrape:
	python -m src.scraper

scrape-test:
	python -m src.scraper --max-events 5

clean-data:
	python src/clean_ufc_data.py

train:
	python src/train_model.py

train-lite:
	python src/train_lite_modelV2.py

# Usage: make predict INPUT=data/ufc326.csv
# Optional: make predict INPUT=data/ufc326.csv MODEL=lite EVENT="UFC 326"
predict:
	python -m src.predict --input $(INPUT) \
		$(if $(MODEL),--model $(MODEL),) \
		$(if $(EVENT),--event "$(EVENT)",) \
		$(if $(ODDS_FORMAT),--odds-format $(ODDS_FORMAT),) \
		$(if $(OUTPUT),--output $(OUTPUT),)

analysis:
	python src/feature_importance.py

# ── Docker ───────────────────────────────────────────────────────────────────

docker-build:
	docker compose build

docker-scrape:
	docker compose run --rm scraper

docker-scrape-test:
	docker compose run --rm scraper python -m src.scraper --max-events 5

docker-clean:
	docker compose run --rm ml python src/clean_ufc_data.py

docker-train:
	docker compose run --rm ml python src/train_model.py

docker-train-lite:
	docker compose run --rm ml python src/train_lite_modelV2.py

# Usage: make docker-predict INPUT=data/ufc326.csv
docker-predict:
	docker compose run --rm ml python -m src.predict --input $(INPUT) \
		$(if $(MODEL),--model $(MODEL),) \
		$(if $(EVENT),--event "$(EVENT)",) \
		$(if $(ODDS_FORMAT),--odds-format $(ODDS_FORMAT),) \
		$(if $(OUTPUT),--output $(OUTPUT),)

docker-jupyter:
	docker compose up jupyter

docker-down:
	docker compose down

docker-delete:
	docker compose down -v
