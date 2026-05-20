# UFC-ML Webapp Modernization Roadmap

## Vision

Transform UFC-ML from a collection of CLI scripts into a **deployable internal-ops web application** with a FastAPI backend and React+TypeScript frontend. The system will support async job execution for long-running operations (scraping, training, bulk prediction), maintain a hybrid NeonDB + file storage architecture, and provide a clean foundation for later public-facing features.

**Key Principles**

- **API-first, async-friendly**: Keep synchronous endpoints fast; offload heavy computation to job queues.
- **Internal ops console first**: MVP targets team-internal workflows (prediction runner, job control), not consumer product.
- **Data as first-class artifact**: Track lineage, versions, and run metadata explicitly; enable reproducibility and audit trails.
- **Incremental ingestion**: One-time historical backfill, then lightweight daily updates; avoid redundant scraping.
- **Testable services**: Modularize around domain boundaries; enable unit testing and clear contracts.

---

## Phase 0: Architecture & Contracts

**Goal**: Define service boundaries, API contracts, database schema, model versioning strategy, and deployment topology.

**Decisions to Finalize**

1. **Service Boundaries**
   - **API Service**: FastAPI server handling synchronous and async endpoints.
   - **Job Worker**: Background process (Celery, RQ, or APScheduler) executing long-running ops.
   - **Model Store**: File storage (S3, local volume) with versioned artifacts and metadata.
   - **Data Store**: NeonDB for operational data; CSV/object storage for bulk model training data.
   - **Scheduler**: Cron or Airflow for recurring jobs; manual trigger API for on-demand.

2. **Endpoint Scope**
   - **Synchronous (fast, API-backed)**
     - `GET /health` – Health check for load balancers.
     - `GET /ready` – Readiness check; confirms model loaded and DB accessible.
     - `GET /api/model-info` – Return feature schema, training date, metrics (ROC-AUC, log loss).
     - `POST /api/predict` – Single/small-batch inference on provided features; returns probabilities.
     - `GET /api/predictions` – Retrieve recent predictions (last N, by event, by date range).
   - **Asynchronous (job-backed; return 202 + task_id)**
     - `POST /api/jobs/scrape` – Queue incremental UFC Stats scrape; return task_id for polling.
     - `POST /api/jobs/transform` – Queue data cleaning + feature engineering; depends on scraped data.
     - `POST /api/jobs/train` – Retrain model with current features; return task_id and metadata endpoint.
     - `GET /api/jobs/{task_id}` – Poll job status (queued, running, completed, failed); include progress %.
     - `POST /api/jobs/{task_id}/cancel` – Cancel pending/running job (admin-only).
   - **Admin/Restricted (require authentication)**
     - All `POST /api/jobs/*` endpoints require admin token.
     - Retraining hyperparameter tuning (MVP: not exposed; seed config in environment).
     - Model registry/A-B test routing (Phase 3+).

3. **Database Schema (NeonDB)**
   - **Core Tables** (idempotent upsert keys)
     - `events`: id, event_url, event_name, date, location, scraped_at, created_at.
     - `fights`: id, event_id, fight_url, red_fighter_id, blue_fighter_id, winner (red/blue/draw), method, is_title_bout, total_rounds, scraped_at, created_at.
     - `fighters`: id, fighter_url, name, height_in, weight_lbs, reach_in, slpm, str_acc, td_avg, sub_avg, wins, losses, updated_at, created_at.
     - `fight_stats`: id, fight_id, r_kd, b_kd, r_sig_str, b_sig_str, r_sig_str_acc, b_sig_str_acc, ... (all stat columns).
   - **Metadata Tables**
     - `scrape_runs`: id, started_at, completed_at, status (running/completed/failed), events_processed, fights_processed, errors_json.
     - `training_runs`: id, model_type, started_at, completed_at, status, n_samples, roc_auc, log_loss, model_version, metadata_json.
     - `prediction_batches`: id, model_version, created_at, n_predictions, input_source (api/job/file), job_id.
   - **Audit/Lineage**
     - `data_lineage`: source_table, record_id, run_id, event_id, created_at (tracks which records came from which scrape run).

4. **Model Artifact Versioning**
   - Store model bundles with immutable metadata:
     ```json
     {
       "version": "lite_v2_20260320_143200",
       "model_type": "lite",
       "trained_at": "2026-03-20T14:32:00Z",
       "n_samples": 5420,
       "features": ["is_title_bout", "total_rounds", ...],
       "metrics": {
         "roc_auc": 0.782,
         "log_loss": 0.421,
         "precision": 0.79,
         "recall": 0.75
       },
       "xgboost_version": "3.2.0",
       "training_data_hash": "sha256:abc123..."
     }
     ```
   - Active model symlink: `models/ufc_xgb_lite.joblib` → `models/archive/ufc_xgb_lite_v2_20260320_143200.joblib`.
   - Store metadata as `.json` sidecar and in `training_runs` table.

5. **Authentication Policy**
   - MVP: Simple bearer token for admin endpoints (env var `ADMIN_API_KEY`).
   - Later: OAuth2, RBAC, audit logging.
   - Public endpoints (predictions read) remain unauthenticated in Phase 1.

---

## Phase 0.1: Operation Classification

**Goal**: Decide which operations belong in API, which in jobs, and which offline.

### Synchronous API Operations (Fast, Blocking)

**Why**: Low latency, deterministic results, safe for immediate user feedback.

- `POST /api/predict` – Load model, run inference on feature vector(s), return probabilities immediately. Latency budget: **< 500ms**.
- `GET /api/model-info` – Serve from in-memory cache (refreshed on each training completion). Latency budget: **< 50ms**.
- `GET /api/predictions` (read-only) – Query `prediction_batches` table, return metadata. Latency budget: **< 1s**.
- `GET /health`, `GET /ready` – Status file or in-memory flag. Latency budget: **< 100ms**.

### Asynchronous Job Operations (Long-Running, Non-Blocking)

**Why**: Variable runtime (minutes to hours), safe to queue and poll; unblock client immediately.

- `POST /api/jobs/scrape` – Queue incremental scraper (5–30 min depending on new events). Return `202 Accepted` + job_id. Client polls `GET /api/jobs/{job_id}` for status.
- `POST /api/jobs/transform` – Queue cleaner + feature engineer (2–10 min on 5k fights). Return `202 Accepted`. Depends on prior scrape.
- `POST /api/jobs/train` – Queue retraining (5–15 min on CPU). Return `202 Accepted`. Depends on transformed data.
- `POST /api/jobs/backfill` – Bulk prediction job on provided CSV (10 min for 1k fights). Return `202 Accepted`. **Not in MVP** (manual only).

### Offline / Pre-Deployment Operations (Manual, Not API)

**Why**: One-time, high effort, or risky; run outside production traffic.

- **Initial historical backfill**: `python -m src.scraper --max-events 0` (scrape all events). Run in pre-prod, store results.
- **Data schema remediation**: Fix missing weight classes, handle outlier fighters, backfill missing stats. Manual SQL/script.
- **Model experimentation**: Hyperparameter grids, feature selection. Run in Jupyter notebooks locally or in staging.
- **Database migrations**: Schema changes, reindexing. Alembic-powered, versioned, tested in staging.

### Intentionally NOT Exposed in MVP

**Why**: Too risky for public or early internal use; requires mature monitoring/rollback first.

- Arbitrary hyperparameter training endpoint (risks unstable models; require explicit admin workflow and A/B testing first).
- Direct model deletion/overwrite endpoint (risk of data loss; require audit trail + approval).
- Scraper selector switching (move to config; restart API to change scraper version).
- Raw database query endpoint (no federation; encourage API-only access for safety).

---

## Phase 1: Pipeline Hardening

**Goal**: Refactor existing scripts into reusable, testable service modules with centralized config, validation, and error handling.

**Deliverables**

### Phase 1.0: Configuration & Constants Centralization

**Why**: Remove hardcoded paths and feature lists scattered across 12 files; enable environment-based config for different deployment tiers.

**Actions**

1. Create `src/config.py`:

   ```python
   import os
   from pathlib import Path
   from dataclasses import dataclass

   @dataclass
   class Config:
       PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
       DATA_DIR: Path = Path(os.getenv('UFC_DATA_DIR', PROJECT_ROOT / 'data'))
       MODEL_DIR: Path = Path(os.getenv('UFC_MODEL_DIR', PROJECT_ROOT / 'models'))
       LOGS_DIR: Path = Path(os.getenv('UFC_LOGS_DIR', PROJECT_ROOT / 'logs'))
       DB_URL: str = os.getenv('DATABASE_URL', 'sqlite:///ufc.db')
       LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
       ADMIN_API_KEY: str = os.getenv('ADMIN_API_KEY', 'dev-key-insecure')
       SCRAPER_MAX_RETRIES: int = int(os.getenv('SCRAPER_RETRIES', '3'))
       SCRAPER_BACKOFF_BASE: float = float(os.getenv('SCRAPER_BACKOFF', '2.0'))
       MODEL_VERSION_PREFIX: str = 'lite_v2'

   config = Config()
   ```

2. Create `src/constants.py`:

   ```python
   LITE_MODEL_FEATURES = [
       "is_title_bout", "total_rounds", "age_diff", "height_diff", "reach_diff",
       "SLpM_total_diff", "SApM_total_diff", "sig_str_acc_total_diff", "str_def_total_diff",
       "td_avg_diff", "td_acc_total_diff", "td_def_total_diff", "sub_avg_diff",
       "wins_total_diff", "losses_total_diff",
   ]

   WEIGHT_CLASSES = [
       "Lightweight", "Welterweight", "Middleweight", "Light Heavyweight", "Heavyweight",
       "Featherweight", "Bantamweight", "Flyweight", "Women's Strawweight", "Women's Featherweight",
       "Women's Bantamweight", "Women's Flyweight",
   ]

   SCRAPER_HEADERS = {
       "User-Agent": "Mozilla/5.0 (UFC-ML-Bot/1.0)"
   }
   ```

3. Create `src/schemas.py` (Pydantic models for validation):

   ```python
   from pydantic import BaseModel, Field
   from typing import List

   class FightFeatures(BaseModel):
       is_title_bout: int = Field(..., ge=0, le=1)
       total_rounds: float = Field(..., ge=1)
       age_diff: float
       height_diff: float
       # ... remaining 11 features with type hints and bounds

   class PredictionRequest(BaseModel):
       fights: List[FightFeatures]
       include_odds: bool = False
       model_version: str = "lite"

   class PredictionResponse(BaseModel):
       prob_red_win: float
       prob_blue_win: float
       red_fighter: str
       blue_fighter: str
   ```

4. Update all imports:
   - `train_lite_modelV2.py`: Import `LITE_MODEL_FEATURES` from constants, not hardcode.
   - `predict.py`: Import config paths and feature list.
   - `clean_ufc_data.py`: Import `WEIGHT_CLASSES` from constants.

**Files Modified**

- Create: `src/config.py`, `src/constants.py`, `src/schemas.py`.
- Update: `src/train_lite_modelV2.py`, `src/predict.py`, `src/clean_ufc_data.py`, `src/scraper.py`.

---

### Phase 1.1: Logging & Error Handling Infrastructure

**Why**: Replace `print()` statements with structured logging; enable audit trails and debugging at scale.

**Actions**

1. Create `src/logger.py`:

   ```python
   import logging
   import json
   from config import config

   logging.basicConfig(
       level=getattr(logging, config.LOG_LEVEL),
       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
   )

   def get_logger(name: str) -> logging.Logger:
       return logging.getLogger(name)

   class JSONFormatter(logging.Formatter):
       def format(self, record):
           log_dict = {
               "timestamp": self.formatTime(record),
               "level": record.levelname,
               "logger": record.name,
               "message": record.getMessage(),
               "context": getattr(record, "context", {}),
           }
           return json.dumps(log_dict)
   ```

2. Create `src/errors.py` (custom exceptions):

   ```python
   class UFCMLError(Exception):
       """Base exception for UFC-ML."""
       pass

   class ValidationError(UFCMLError):
       """Feature validation or data quality error."""
       pass

   class ModelNotFoundError(UFCMLError):
       """Model artifact missing or corrupted."""
       pass

   class PredictionError(UFCMLError):
       """Inference failed."""
       pass

   class ScraperError(UFCMLError):
       """Web scraping failed."""
       pass

   class DataPipelineError(UFCMLError):
       """Data transform or load failed."""
       pass
   ```

3. Update scraper with retry logic:

   ```python
   from tenacity import retry, stop_after_attempt, wait_exponential
   from errors import ScraperError
   from logger import get_logger

   logger = get_logger(__name__)

   @retry(
       stop=stop_after_attempt(config.SCRAPER_MAX_RETRIES),
       wait=wait_exponential(multiplier=1, min=2, max=10),
       reraise=True
   )
   def _get_soup(url: str):
       try:
           resp = requests.get(url, headers=HEADERS, timeout=20)
           resp.raise_for_status()
           return BeautifulSoup(resp.text, "html.parser")
       except Exception as e:
           logger.error(f"Failed to fetch {url}", extra={"context": {"url": url, "error": str(e)}})
           raise ScraperError(f"Fetch failed for {url}") from e
   ```

**Files Modified/Created**

- Create: `src/logger.py`, `src/errors.py`.
- Update: `src/scraper.py`, `src/predict.py`, `src/train_lite_modelV2.py`, `src/clean_ufc_data.py`.

---

### Phase 1.2: Consolidate Prediction & Odds Logic

**Why**: Currently 4 near-identical `predict_ufc*.py` scripts and duplicated odds functions across files. Centralize into one reusable service.

**Actions**

1. Create `src/services/predictor.py` (extracted from `predict.py`):

   ```python
   import joblib
   from config import config
   from constants import LITE_MODEL_FEATURES
   from errors import ModelNotFoundError, ValidationError, PredictionError
   from logger import get_logger

   logger = get_logger(__name__)

   class PredictionService:
       def __init__(self, model_version: str = "lite"):
           self.model_version = model_version
           self.model_path = config.MODEL_DIR / "ufc_xgb_lite.joblib"
           self.model_bundle = self._load_model()

       def _load_model(self):
           if not self.model_path.exists():
               raise ModelNotFoundError(f"Model not found at {self.model_path}")
           return joblib.load(self.model_path)

       def predict(self, features_df):
           # Validate features
           required = set(self.model_bundle["features"])
           provided = set(features_df.columns)
           missing = required - provided
           if missing:
               raise ValidationError(f"Missing features: {missing}")

           # Run inference
           try:
               X = features_df[required]
               probs = self.model_bundle["model"].predict_proba(X)[:, 1]
               return probs
           except Exception as e:
               logger.error(f"Prediction failed", extra={"context": {"error": str(e)}})
               raise PredictionError(f"Inference failed: {e}") from e
   ```

2. Consolidate odds logic into `src/services/odds_engine.py`:

   ```python
   # Move and consolidate american_to_payout, compute_ev, best_ev_multi_book, etc.
   # Ensure single source of truth, not duplicated in predict_*.py
   ```

3. Delete or deprecate:
   - `src/predict_ufc325.py`, `src/predict_ufc324.py`, `src/predict_qatar.py`, `src/predict_lite.py`.
   - Update Makefile and docs to point to `python -m src.predict --input-file data/ufc325.csv`.

4. Unify `src/predict.py` to use new services:

   ```python
   from services.predictor import PredictionService
   from services.odds_engine import compute_ev_multi_book

   def main(args):
       predictor = PredictionService(model_version=args.model)
       input_df = pd.read_csv(args.input_file)
       probs = predictor.predict(input_df)
       # ... continue with EV calculation using odds_engine
   ```

**Files Modified/Created**

- Create: `src/services/predictor.py`, `src/services/odds_engine.py`, `src/services/__init__.py`.
- Update: `src/predict.py` (remove duplication).
- Delete: `src/predict_ufc*.py` (consolidate to one entry point).

---

### Phase 1.3: Implement Feature & Data Validation

**Why**: Prevent silent failures; fail fast on missing/invalid data with clear error messages.

**Actions**

1. Create `src/validators.py`:

   ```python
   import pandas as pd
   from constants import LITE_MODEL_FEATURES
   from errors import ValidationError

   def validate_features(df: pd.DataFrame, required_features: list) -> None:
       """Raise ValidationError if missing or NaN features."""
       missing = set(required_features) - set(df.columns)
       if missing:
           raise ValidationError(f"Missing columns: {missing}")

       # Check for NaN/inf
       for col in required_features:
           if df[col].isnull().any():
               raise ValidationError(f"NaN values in '{col}'")
           if df[col].dtype in [float, int] and pd.isnull(df[col]).any():
               raise ValidationError(f"Invalid numeric values in '{col}'")

   def validate_odds_format(odds_dict: dict) -> None:
       """Validate odds entry (american or decimal)."""
       for fighter_side in ["red", "blue"]:
           if fighter_side not in odds_dict:
               raise ValidationError(f"Missing odds side: {fighter_side}")
           odds = odds_dict[fighter_side]
           if not isinstance(odds, (int, float)):
               raise ValidationError(f"Invalid odds type for {fighter_side}: {type(odds)}")

   def validate_fight_record(raw_fight: dict) -> None:
       """Validate raw scraped fight record before storage."""
       required = ["event_url", "fight_url", "red_fighter_url", "blue_fighter_url", "winner"]
       missing = set(required) - set(raw_fight.keys())
       if missing:
           raise ValidationError(f"Incomplete fight record; missing: {missing}")
   ```

2. Integrate into services:
   - `scraper.py`: Call `validate_fight_record()` before storing fight.
   - `predictor.py`: Call `validate_features()` before inference.
   - `clean_ufc_data.py`: Call `validate_features()` on output before save.

**Files Modified/Created**

- Create: `src/validators.py`.
- Update: `src/scraper.py`, `src/services/predictor.py`, `src/clean_ufc_data.py`.

---

### Phase 1.4: Modularize Cleaner & Trainer

**Why**: Separate concerns; make reusable by API workers and batch jobs.

**Actions**

1. Create `src/services/cleaner.py` (extracted from `clean_ufc_data.py`):

   ```python
   import pandas as pd
   from config import config
   from constants import WEIGHT_CLASSES, LITE_MODEL_FEATURES
   from validators import validate_features

   class DataCleaner:
       def clean(self, raw_csv_path: str) -> pd.DataFrame:
           """Load raw fights CSV, engineer features, return cleaned DataFrame."""
           df = pd.read_csv(raw_csv_path)

           # Validate input
           required_raw_cols = ["event_name", "r_fighter", "b_fighter", "winner", ...]
           validate_features(df, required_raw_cols)

           # Filter valid winners
           df = df[df["winner"].isin(["Red", "Blue"])].copy()
           df["win_red"] = (df["winner"] == "Red").astype(int)

           # Create diffs
           stat_cols = ["age", "height_in", "reach_in", "slpm", ...]
           for stat in stat_cols:
               df[f"{stat}_diff"] = df[f"r_{stat}"] - df[f"b_{stat}"]

           # One-hot encode weight classes
           df = pd.get_dummies(df, columns=["weight_class"], prefix="wc")

           # Drop rows with NaN in key features
           df = df.dropna(subset=LITE_MODEL_FEATURES + ["win_red"])

           return df
   ```

2. Create `src/services/trainer.py` (extracted from `train_lite_modelV2.py`):

   ```python
   import joblib
   from datetime import datetime
   from xgboost import XGBClassifier
   from sklearn.model_selection import train_test_split
   from sklearn.metrics import roc_auc_score, log_loss
   from config import config
   from constants import LITE_MODEL_FEATURES
   from logger import get_logger

   logger = get_logger(__name__)

   class ModelTrainer:
       def train(self, features_csv: str) -> dict:
           """Train model, save bundle, return metadata."""
           df = pd.read_csv(features_csv)

           X = df[LITE_MODEL_FEATURES]
           y = df["win_red"]

           X_train, X_test, y_train, y_test = train_test_split(
               X, y, test_size=0.2, stratify=y, random_state=42
           )

           clf = XGBClassifier(
               n_estimators=600,
               max_depth=3,
               learning_rate=0.05,
               subsample=0.9,
               random_state=42,
               n_jobs=4
           )
           clf.fit(X_train, y_train)

           # Evaluate
           y_pred_proba = clf.predict_proba(X_test)[:, 1]
           roc_auc = roc_auc_score(y_test, y_pred_proba)
           log_loss_val = log_loss(y_test, y_pred_proba)

           # Create metadata
           version = f"{config.MODEL_VERSION_PREFIX}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
           metadata = {
               "version": version,
               "model_type": "lite",
               "trained_at": datetime.now().isoformat(),
               "n_samples": len(df),
               "features": LITE_MODEL_FEATURES,
               "metrics": {
                   "roc_auc": float(roc_auc),
                   "log_loss": float(log_loss_val),
               },
               "xgboost_version": "3.2.0",
           }

           # Save bundle
           bundle = {"model": clf, "features": LITE_MODEL_FEATURES, "metadata": metadata}
           model_path = config.MODEL_DIR / "ufc_xgb_lite.joblib"
           joblib.dump(bundle, model_path)
           logger.info(f"Model trained and saved: {version}", extra={"context": metadata})

           return metadata
   ```

3. Update CLI scripts to use services:

   ```python
   # clean_ufc_data.py
   from services.cleaner import DataCleaner
   cleaner = DataCleaner()
   df_clean = cleaner.clean("data/raw_fights.csv")
   df_clean.to_csv("data/ufc_features.csv", index=False)

   # train_lite_modelV2.py
   from services.trainer import ModelTrainer
   trainer = ModelTrainer()
   metadata = trainer.train("data/ufc_features.csv")
   ```

**Files Modified/Created**

- Create: `src/services/cleaner.py`, `src/services/trainer.py`.
- Update: `src/clean_ufc_data.py`, `src/train_lite_modelV2.py`.

---

**Phase 1 Verification**

- [ ] All hardcoded paths use `config.py` via `config.DATA_DIR`, `config.MODEL_DIR`.
- [ ] All feature lists import from `constants.LITE_MODEL_FEATURES`.
- [ ] All errors raise custom exceptions, caught and logged with context.
- [ ] All `print()` statements replaced with `logger.info/error/debug`.
- [ ] Single `src/services/predictor.py` used by all predict paths (no duplication).
- [ ] `src/validators.py` called at data boundaries (scraper output, predictor input, cleaner output).
- [ ] Unit tests pass for each service module.

---

## Phase 1.5: Web Scraper Resilience

**Goal**: Add checkpoint/resume capability, incremental ingestion mode, and retry logic.

**Actions**

1. Add scraper state tracking:

   ```python
   # src/scraper.py
   class ScraperState:
       def __init__(self, state_file: str = "scraper_state.json"):
           self.state_file = state_file
           self.data = self._load()

       def _load(self):
           if Path(self.state_file).exists():
               return json.load(open(self.state_file))
           return {"last_event_index": 0, "last_event_id": None, "last_scraped": None}

       def save(self):
           with open(self.state_file, 'w') as f:
               json.dump(self.data, f)

       def mark_event_complete(self, event_id, event_index):
           self.data["last_event_id"] = event_id
           self.data["last_event_index"] = event_index
           self.data["last_scraped"] = datetime.now().isoformat()
           self.save()
   ```

2. Add incremental mode:

   ```python
   def scrape_all(max_events=None, incremental=True):
       state = ScraperState()
       start_index = state.data["last_event_index"] if incremental else 0

       events = scrape_event_urls()
       new_events_count = 0

       for i, event in enumerate(events[start_index:], start=start_index):
           if max_events and new_events_count >= max_events:
               break

           try:
               fights = scrape_event_fights(event["url"])
               for fight in fights:
                   details = scrape_fight_details(fight["url"])
                   # ... store fight
               new_events_count += 1
               state.mark_event_complete(event["id"], i)
           except Exception as e:
               logger.error(f"Failed event {event['id']}", extra={"context": {"error": str(e)}})
               # Mark failure, continue
               state.save()
               raise

       logger.info(f"Scrape complete: {new_events_count} new events", extra={"context": {"new_events": new_events_count}})
   ```

3. Add `--resume-from EVENT_ID` CLI flag:
   ```python
   # Allow restart from specific event if scraper crashes mid-run
   ```

**Files Modified**

- Update: `src/scraper.py`.

---

## Phase 2: FastAPI Backend MVP

**Goal**: Expose core functionality as REST API with async job infrastructure.

**Deliverables**

### Phase 2.0: API Structure & Scaffolding

**Actions**

1. Create `src/api/app.py`:

   ```python
   from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
   from fastapi.middleware.cors import CORSMiddleware
   from contextlib import asynccontextmanager
   import logging

   from config import config
   from services.predictor import PredictionService
   from api import health, predict, jobs

   logger = logging.getLogger(__name__)

   # Lifespan for startup/shutdown
   @asynccontextmanager
   async def lifespan(app: FastAPI):
       # Startup
       logger.info("API starting up")
       # Preload model
       predictor = PredictionService()
       app.state.predictor = predictor
       yield
       # Shutdown
       logger.info("API shutting down")

   app = FastAPI(
       title="UFC-ML API",
       description="Internal ops API for predictions, data scraping, and model training.",
       version="0.1.0",
       lifespan=lifespan
   )

   # CORS for frontend
   app.add_middleware(
       CORSMiddleware,
       allow_origins=["http://localhost:3000", "https://your-frontend-domain.com"],
       allow_methods=["*"],
       allow_headers=["*"],
       allow_credentials=True,
   )

   # Routes
   app.include_router(health.router)
   app.include_router(predict.router)
   app.include_router(jobs.router)

   if __name__ == "__main__":
       import uvicorn
       uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
   ```

2. Create route modules:
   - `src/api/routers/health.py` – `GET /health`, `GET /ready`.
   - `src/api/routers/predict.py` – `POST /api/predict`, `GET /api/predictions`.
   - `src/api/routers/jobs.py` – `POST /api/jobs/scrape`, `POST /api/jobs/train`, etc.
   - `src/api/routers/auth.py` – Authentication helpers.

3. Create `src/api/dependencies.py`:

   ```python
   from fastapi import Header, HTTPException
   from config import config

   def verify_admin_token(authorization: str = Header(...)):
       """Validate admin API key."""
       if authorization != f"Bearer {config.ADMIN_API_KEY}":
           raise HTTPException(status_code=401, detail="Unauthorized")
       return True
   ```

4. Create `src/api/schemas.py` (Pydantic models for request/response):

   ```python
   from pydantic import BaseModel
   from typing import List, Optional
   from enum import Enum

   class JobStatus(str, Enum):
       QUEUED = "queued"
       RUNNING = "running"
       COMPLETED = "completed"
       FAILED = "failed"

   class PredictionRequest(BaseModel):
       fights: List[dict]
       model_version: str = "lite"

   class PredictionResponse(BaseModel):
       red_fighter: str
       blue_fighter: str
       prob_red_win: float
       prob_blue_win: float
       model_version: str

   class ScrapeJobRequest(BaseModel):
       max_events: Optional[int] = None
       force_full_rescrape: bool = False

   class JobResponse(BaseModel):
       job_id: str
       status: JobStatus
       created_at: str
       updated_at: Optional[str]
       progress: Optional[dict] = None
       result: Optional[dict] = None
       error: Optional[str] = None
   ```

**Files Created**

- Create: `src/api/app.py`, `src/api/__init__.py`, `src/api/dependencies.py`, `src/api/schemas.py`.
- Create: `src/api/routers/health.py`, `src/api/routers/predict.py`, `src/api/routers/jobs.py`, `src/api/routers/auth.py`.

---

### Phase 2.1: Synchronous Endpoints

**Actions**

1. `src/api/routers/health.py`:

   ```python
   from fastapi import APIRouter
   from datetime import datetime

   router = APIRouter(tags=["health"])

   @router.get("/health")
   def health_check():
       """Basic health check for load balancers."""
       return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

   @router.get("/ready")
   def readiness_check():
       """Full readiness check: model loaded, DB accessible."""
       try:
           predictor = PredictionService()  # Fails if model missing
           # TODO: Check DB connection
           return {"status": "ready"}
       except Exception as e:
           return {"status": "not_ready", "error": str(e)}
   ```

2. `src/api/routers/predict.py`:

   ```python
   from fastapi import APIRouter, Depends, HTTPException
   from api.schemas import PredictionRequest, PredictionResponse
   from api.dependencies import verify_admin_token
   from services.predictor import PredictionService
   from services.odds_engine import compute_ev_multi_book
   import pandas as pd

   router = APIRouter(prefix="/api", tags=["predict"])

   @router.post("/predict", response_model=List[PredictionResponse])
   async def predict_fights(req: PredictionRequest):
       """Predict fight outcomes for provided feature vectors."""
       try:
           predictor = PredictionService(model_version=req.model_version)
           df = pd.DataFrame(req.fights)
           probs = predictor.predict(df)

           results = []
           for i, (idx, row) in enumerate(df.iterrows()):
               results.append(PredictionResponse(
                   red_fighter=row.get("red_fighter", "Unknown"),
                   blue_fighter=row.get("blue_fighter", "Unknown"),
                   prob_red_win=float(probs[i]),
                   prob_blue_win=float(1 - probs[i]),
                   model_version=req.model_version
               ))
           return results
       except ValidationError as e:
           raise HTTPException(status_code=400, detail=str(e))
       except PredictionError as e:
           raise HTTPException(status_code=500, detail=str(e))

   @router.get("/model-info")
   async def model_info():
       """Return active model metadata and features."""
       predictor = PredictionService()
       return predictor.model_bundle.get("metadata", {})

   @router.get("/predictions")
   async def get_predictions(limit: int = 100, offset: int = 0):
       """Retrieve recent predictions (metadata only; admin can query full results)."""
       # TODO: Query prediction_batches table
       return {"predictions": [], "total": 0}
   ```

**Files Created/Updated**

- Create: `src/api/routers/health.py`, `src/api/routers/predict.py`.

---

### Phase 2.2: Asynchronous Job Infrastructure

**Actions**

1. Choose job backend (recommend **APScheduler** for MVP simplicity, upgrade to Celery if needed):

   ```bash
   pip install apscheduler redis
   ```

2. Create `src/workers/job_queue.py`:

   ```python
   import uuid
   from datetime import datetime
   from enum import Enum
   from dataclasses import dataclass, asdict
   import json
   from pathlib import Path
   import redis

   class JobStatus(str, Enum):
       QUEUED = "queued"
       RUNNING = "running"
       COMPLETED = "completed"
       FAILED = "failed"

   @dataclass
   class Job:
       job_id: str
       job_type: str  # "scrape", "train", "transform"
       status: JobStatus
       created_at: str
       updated_at: str
       progress: dict = None
       result: dict = None
       error: str = None
       payload: dict = None

   class JobQueue:
       def __init__(self, redis_url: str = "redis://localhost:6379"):
           self.redis_client = redis.from_url(redis_url)

       def enqueue(self, job_type: str, payload: dict = None) -> str:
           job_id = str(uuid.uuid4())
           job = Job(
               job_id=job_id,
               job_type=job_type,
               status=JobStatus.QUEUED,
               created_at=datetime.utcnow().isoformat(),
               updated_at=datetime.utcnow().isoformat(),
               payload=payload,
           )
           self.redis_client.set(f"job:{job_id}", json.dumps(asdict(job)))
           self.redis_client.lpush(f"queue:{job_type}", job_id)
           return job_id

       def get_job(self, job_id: str) -> Job:
           data = self.redis_client.get(f"job:{job_id}")
           if not data:
               return None
           return Job(**json.loads(data))

       def update_job(self, job_id: str, status: JobStatus, progress: dict = None, result: dict = None, error: str = None):
           job = self.get_job(job_id)
           job.status = status
           job.updated_at = datetime.utcnow().isoformat()
           if progress:
               job.progress = progress
           if result:
               job.result = result
           if error:
               job.error = error
           self.redis_client.set(f"job:{job_id}", json.dumps(asdict(job)))
   ```

3. Create `src/workers/executor.py` (runs jobs; can be separate process or async task):

   ```python
   from job_queue import JobQueue, JobStatus
   from services.scraper import Scraper
   from services.cleaner import DataCleaner
   from services.trainer import ModelTrainer
   from logger import get_logger

   logger = get_logger(__name__)
   queue = JobQueue()

   def execute_job(job_id: str):
       """Worker function: process queued job."""
       job = queue.get_job(job_id)
       if not job:
           return

       queue.update_job(job_id, JobStatus.RUNNING)

       try:
           if job.job_type == "scrape":
               result = execute_scrape_job(job)
           elif job.job_type == "transform":
               result = execute_transform_job(job)
           elif job.job_type == "train":
               result = execute_train_job(job)
           else:
               raise ValueError(f"Unknown job type: {job.job_type}")

           queue.update_job(job_id, JobStatus.COMPLETED, result=result)
           logger.info(f"Job completed: {job_id}", extra={"context": {"job_id": job_id}})
       except Exception as e:
           queue.update_job(job_id, JobStatus.FAILED, error=str(e))
           logger.error(f"Job failed: {job_id}", extra={"context": {"job_id": job_id, "error": str(e)}})

   def execute_scrape_job(job):
       scraper = Scraper()
       max_events = job.payload.get("max_events")
       force_full = job.payload.get("force_full_rescrape", False)

       events_scraped = 0
       fights_scraped = 0

       # TODO: Implement with progress callback
       scraper.scrape_all(max_events=max_events, incremental=not force_full)

       return {
           "events_scraped": events_scraped,
           "fights_scraped": fights_scraped,
       }

   def execute_transform_job(job):
       cleaner = DataCleaner()
       df = cleaner.clean("data/raw_fights.csv")
       df.to_csv("data/ufc_features.csv", index=False)
       return {"rows_processed": len(df)}

   def execute_train_job(job):
       trainer = ModelTrainer()
       metadata = trainer.train("data/ufc_features.csv")
       return metadata
   ```

4. Create `src/api/routers/jobs.py`:

   ```python
   from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
   from api.schemas import ScrapeJobRequest, JobResponse
   from api.dependencies import verify_admin_token
   from workers.job_queue import JobQueue
   from workers.executor import execute_job

   router = APIRouter(prefix="/api", tags=["jobs"])
   queue = JobQueue()

   @router.post("/jobs/scrape", response_model=JobResponse, status_code=202)
   async def scrape_job(
       req: ScrapeJobRequest,
       background_tasks: BackgroundTasks,
       _=Depends(verify_admin_token)
   ):
       """Queue incremental or full scrape job; return immediately with job_id."""
       job_id = queue.enqueue("scrape", payload=req.dict())
       background_tasks.add_task(execute_job, job_id)

       job = queue.get_job(job_id)
       return JobResponse(
           job_id=job_id,
           status=job.status,
           created_at=job.created_at,
       )

   @router.post("/jobs/transform", response_model=JobResponse, status_code=202)
   async def transform_job(
       background_tasks: BackgroundTasks,
       _=Depends(verify_admin_token)
   ):
       """Queue data transform job."""
       job_id = queue.enqueue("transform")
       background_tasks.add_task(execute_job, job_id)

       job = queue.get_job(job_id)
       return JobResponse(
           job_id=job_id,
           status=job.status,
           created_at=job.created_at,
       )

   @router.post("/jobs/train", response_model=JobResponse, status_code=202)
   async def train_job(
       background_tasks: BackgroundTasks,
       _=Depends(verify_admin_token)
   ):
       """Queue model training job."""
       job_id = queue.enqueue("train")
       background_tasks.add_task(execute_job, job_id)

       job = queue.get_job(job_id)
       return JobResponse(
           job_id=job_id,
           status=job.status,
           created_at=job.created_at,
       )

   @router.get("/jobs/{job_id}", response_model=JobResponse)
   async def get_job_status(job_id: str):
       """Poll job status."""
       job = queue.get_job(job_id)
       if not job:
           raise HTTPException(status_code=404, detail="Job not found")

       return JobResponse(
           job_id=job.job_id,
           status=job.status,
           created_at=job.created_at,
           updated_at=job.updated_at,
           progress=job.progress,
           result=job.result,
           error=job.error,
       )

   @router.post("/jobs/{job_id}/cancel", response_model=dict)
   async def cancel_job(job_id: str, _=Depends(verify_admin_token)):
       """Cancel pending/running job (admin-only)."""
       job = queue.get_job(job_id)
       if not job:
           raise HTTPException(status_code=404, detail="Job not found")
       if job.status not in ["queued", "running"]:
           raise HTTPException(status_code=400, detail="Cannot cancel completed job")
       # TODO: Implement cancellation
       return {"status": "cancelled", "job_id": job_id}
   ```

**Files Created**

- Create: `src/workers/job_queue.py`, `src/workers/executor.py`, `src/api/routers/jobs.py`.

---

### Phase 2.3: Deployment & Environment Setup

**Actions**

1. Update `requirements.in`:

   ```
   # Existing
   xgboost-cpu==3.2.0
   pandas==2.3.3
   numpy==1.26.4
   scikit-learn==1.5.0
   beautifulsoup4==4.12.2
   requests==2.31.0

   # New - Backend
   fastapi==0.104.1
   uvicorn==0.24.0
   pydantic==2.5.0
   sqlalchemy==2.0.23
   psycopg2-binary==2.9.9  # PostgreSQL adapter for NeonDB
   alembic==1.13.1
   redis==5.0.1
   apscheduler==3.10.4
   python-jose==3.3.0
   python-multipart==0.0.6
   tenacity==8.2.3
   ```

2. Recompile requirements:

   ```bash
   pip-compile --strip-extras --no-emit-trusted-host --no-header requirements.in -o requirements.txt
   ```

3. Update `Dockerfile` to support API service:

   ```dockerfile
   FROM python:3.12-slim as runtime
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   ENV PYTHONUNBUFFERED=1
   EXPOSE 8000
   ENTRYPOINT ["python", "-m", "src.api.app"]
   ```

4. Update `docker-compose.yml`:

   ```yaml
   version: "3.9"
   services:
     api:
       build:
         context: .
         target: runtime
       ports:
         - "8000:8000"
       environment:
         DATABASE_URL: "${DATABASE_URL}"
         ADMIN_API_KEY: "${ADMIN_API_KEY}"
         LOG_LEVEL: "INFO"
       volumes:
         - ./data:/app/data
         - ./models:/app/models
       depends_on:
         - redis

     worker:
       build:
         context: .
         target: runtime
       command: python -m src.workers.executor
       environment:
         DATABASE_URL: "${DATABASE_URL}"
         LOG_LEVEL: "INFO"
       volumes:
         - ./data:/app/data
         - ./models:/app/models
       depends_on:
         - redis

     redis:
       image: "redis:7-alpine"
       ports:
         - "6379:6379"
       volumes:
         - redis_data:/data

     scraper:
       build:
         context: .
         target: runtime
       command: python -m src.scraper
       volumes:
         - ./data:/app/data

     jupyter:
       build:
         context: .
         target: dev
       ports:
         - "8888:8888"
       command: jupyter lab --ip=0.0.0.0 --allow-root --no-browser
       volumes:
         - ./:/app

   volumes:
     redis_data:
   ```

5. Create `.env.example`:

   ```env
   DATABASE_URL=postgresql://user:password@localhost/ufc_ml
   ADMIN_API_KEY=your-secure-key-here
   LOG_LEVEL=INFO
   UFC_DATA_DIR=./data
   UFC_MODEL_DIR=./models
   ```

6. Update `Makefile` with API targets:

   ```makefile
   .PHONY: api-dev
   api-dev:
   	python -m uvicorn src.api.app:app --reload --port 8000

   .PHONY: api-prod
   api-prod:
   	python -m uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --workers 4

   .PHONY: worker
   worker:
   	python -m src.workers.executor

   .PHONY: db-migrate
   db-migrate:
   	alembic upgrade head
   ```

**Files Modified/Created**

- Update: `requirements.in`, `Dockerfile`, `docker-compose.yml`, `Makefile`.
- Create: `.env.example`.

---

**Phase 2 Verification**

- [ ] API starts without errors: `make api-dev`.
- [ ] `GET /health` responds with HTTP 200.
- [ ] `GET /ready` responds with model loaded confirmation.
- [ ] `POST /api/predict` accepts valid features and returns probabilities.
- [ ] `POST /api/jobs/scrape` returns 202 + job_id.
- [ ] `GET /api/jobs/{job_id}` polls status correctly.
- [ ] Admin endpoints reject requests without valid `ADMIN_API_KEY`.
- [ ] Backend worker can be started: `make worker`.
- [ ] Redis connectivity verified.

---

## Phase 3: Recurring Operations & Scheduling

**Goal**: Automate scraping, data transformation, and retraining with smart scheduling that avoids redundant work.

**Deliverables**

### Phase 3.0: Scheduling Strategy

**Decisions**

1. **Scheduler choice**: APScheduler in-app + persistent state file for MVP; upgrade to Airflow if multi-step DAG complexity grows.

2. **Retraining trigger**:
   - Manual: `POST /api/jobs/train` endpoint (admin).
   - Scheduled: Weekly on Monday 03:00 UTC by default; skip if no new data since last train.

3. **Scraping schedule**:
   - Daily at 02:00 UTC.
   - Incremental mode: fast exit if no new events.
   - Force full rescrape monthly to catch data corrections.

4. **Data quality gates**:
   - Skip retraining if new data has > 5% missing values.
   - Skip retraining if train/test AUC fails to exceed floor (0.70).

### Phase 3.1: Scheduler Implementation

**Actions**

1. Create `src/scheduler/scheduler.py`:

   ```python
   from apscheduler.schedulers.background import BackgroundScheduler
   from apscheduler.triggers.cron import CronTrigger
   from logger import get_logger
   from workers.job_queue import JobQueue
   from workers.executor import execute_job

   logger = get_logger(__name__)
   queue = JobQueue()

   class UFCScheduler:
       def __init__(self):
           self.scheduler = BackgroundScheduler()

       def start(self):
           """Start background scheduler."""
           self.scheduler.add_job(
               self.scrape_job,
               CronTrigger(hour=2, minute=0),  # Daily 02:00 UTC
               id="daily_scrape",
               name="Incremental scrape"
           )

           self.scheduler.add_job(
               self.train_job,
               CronTrigger(day_of_week="0", hour=3, minute=0),  # Monday 03:00 UTC
               id="weekly_train",
               name="Weekly retraining"
           )

           self.scheduler.add_job(
               self.full_scrape_job,
               CronTrigger(day=1, hour=4, minute=0),  # 1st of month 04:00 UTC
               id="monthly_full_scrape",
               name="Monthly full rescrape for corrections"
           )

           self.scheduler.start()
           logger.info("Scheduler started")

       def scrape_job(self):
           """Queue incremental scrape."""
           logger.info("Queuing daily incremental scrape")
           job_id = queue.enqueue("scrape", payload={"max_events": None, "force_full_rescrape": False})
           execute_job(job_id)

       def train_job(self):
           """Queue training with quality gates."""
           logger.info("Checking if retraining is needed")

           # Check if new data exists since last training
           last_scrape = self.get_last_scrape_time()
           last_train = self.get_last_training_time()
           if last_scrape and last_train and last_scrape < last_train:
               logger.info("No new data since last training; skipping")
               return

           # Check data quality
           if not self.check_data_quality():
               logger.warning("Data quality gate failed; skipping training")
               return

           logger.info("Queuing training job")
           job_id = queue.enqueue("train")
           execute_job(job_id)

       def full_scrape_job(self):
           """Force full rescrape for corrections."""
           logger.info("Queuing monthly full rescrape")
           job_id = queue.enqueue("scrape", payload={"force_full_rescrape": True})
           execute_job(job_id)

       def get_last_scrape_time(self):
           # TODO: Query DB for latest scrape_runs record
           pass

       def get_last_training_time(self):
           # TODO: Query DB for latest training_runs record
           pass

       def check_data_quality(self):
           # TODO: Check for > 5% missing values in features
           return True

       def shutdown(self):
           self.scheduler.shutdown()
   ```

2. Integrate into FastAPI app (`src/api/app.py`):

   ```python
   from scheduler.scheduler import UFCScheduler

   scheduler_instance = None

   @asynccontextmanager
   async def lifespan(app: FastAPI):
       global scheduler_instance
       # Startup
       scheduler_instance = UFCScheduler()
       scheduler_instance.start()
       yield
       # Shutdown
       if scheduler_instance:
           scheduler_instance.shutdown()

   app = FastAPI(..., lifespan=lifespan)
   ```

**Files Created**

- Create: `src/scheduler/scheduler.py`, `src/scheduler/__init__.py`.

---

### Phase 3.2: Database Migrations (Alembic)

**Actions**

1. Initialize Alembic:

   ```bash
   alembic init alembic
   ```

2. Configure `alembic.ini` to use `DATABASE_URL` from env.

3. Create migration for core schema:

   ```bash
   alembic revision --autogenerate -m "Initial schema: events, fights, fighters, runs"
   ```

4. Define models in `src/models/db.py`:

   ```python
   from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
   from sqlalchemy.ext.declarative import declarative_base
   from datetime import datetime

   Base = declarative_base()

   class Event(Base):
       __tablename__ = "events"
       id = Column(Integer, primary_key=True)
       event_url = Column(String, unique=True)
       event_name = Column(String)
       date = Column(DateTime)
       location = Column(String)
       scraped_at = Column(DateTime, default=datetime.utcnow)
       created_at = Column(DateTime, default=datetime.utcnow)

   class Fight(Base):
       __tablename__ = "fights"
       id = Column(Integer, primary_key=True)
       event_id = Column(Integer, ForeignKey("events.id"))
       fight_url = Column(String, unique=True)
       red_fighter_id = Column(Integer, ForeignKey("fighters.id"))
       blue_fighter_id = Column(Integer, ForeignKey("fighters.id"))
       winner = Column(String)  # red, blue, draw
       method = Column(String)
       is_title_bout = Column(Boolean)
       total_rounds = Column(Integer)
       scraped_at = Column(DateTime, default=datetime.utcnow)
       created_at = Column(DateTime, default=datetime.utcnow)

   class Fighter(Base):
       __tablename__ = "fighters"
       id = Column(Integer, primary_key=True)
       fighter_url = Column(String, unique=True)
       name = Column(String)
       height_in = Column(Float)
       weight_lbs = Column(Float)
       reach_in = Column(Float)
       slpm = Column(Float)
       str_acc = Column(Float)
       td_avg = Column(Float)
       sub_avg = Column(Float)
       wins = Column(Integer)
       losses = Column(Integer)
       updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
       created_at = Column(DateTime, default=datetime.utcnow)

   class ScrapeRun(Base):
       __tablename__ = "scrape_runs"
       id = Column(Integer, primary_key=True)
       started_at = Column(DateTime, default=datetime.utcnow)
       completed_at = Column(DateTime)
       status = Column(String)  # running, completed, failed
       events_processed = Column(Integer)
       fights_processed = Column(Integer)
       errors_json = Column(String)  # JSON string

   class TrainingRun(Base):
       __tablename__ = "training_runs"
       id = Column(Integer, primary_key=True)
       model_type = Column(String)  # lite, full
       started_at = Column(DateTime, default=datetime.utcnow)
       completed_at = Column(DateTime)
       status = Column(String)  # running, completed, failed
       n_samples = Column(Integer)
       roc_auc = Column(Float)
       log_loss = Column(Float)
       model_version = Column(String)
       metadata_json = Column(String)  # JSON string
   ```

5. Apply migrations:
   ```bash
   alembic upgrade head
   ```

**Files Created/Modified**

- Create: `alembic/`, `src/models/db.py`.
- Update: `src/models/__init__.py`.

---

**Phase 3 Verification**

- [ ] Scheduler starts with FastAPI app.
- [ ] Daily scrape job queues at 02:00 UTC (testable with manual time override).
- [ ] Training job skips if no new data.
- [ ] Full rescrape queues on 1st of month.
- [ ] DB migrations apply cleanly to NeonDB staging.
- [ ] `scrape_runs` and `training_runs` tables record job history.

---

## Phase 4: Testing Strategy

**Goal**: Add pytest suites for utilities, API, and ML-specific tests with golden-file regression fixtures.

**Deliverables**

### Phase 4.0: Test Structure

**Actions**

1. Create `tests/` directory:

   ```
   tests/
   ├── conftest.py
   ├── unit/
   │   ├── test_odds.py
   │   ├── test_validators.py
   │   ├── test_config.py
   │   └── test_schemas.py
   ├── integration/
   │   ├── test_predictor_service.py
   │   ├── test_cleaner_service.py
   │   ├── test_trainer_service.py
   │   └── test_api_endpoints.py
   ├── ml/
   │   ├── test_prediction_determinism.py
   │   └── test_training_metrics.py
   ├── fixtures/
   │   ├── sample_features.csv
   │   ├── sample_predictions.json  # golden file
   │   └── sample_raw_fights.csv
   └── workers/
       └── test_job_queue.py
   ```

2. Create `tests/conftest.py`:

   ```python
   import pytest
   import tempfile
   from pathlib import Path
   import shutil

   @pytest.fixture
   def tmp_project_root(tmp_path):
       """Create temporary project directory with subdirs."""
       (tmp_path / "data").mkdir()
       (tmp_path / "models").mkdir()
       return tmp_path

   @pytest.fixture
   def mock_config(tmp_project_root, monkeypatch):
       """Override config to use temp directory."""
       from config import Config
       monkeypatch.setattr("config.config", Config(
           PROJECT_ROOT=tmp_project_root,
           DATA_DIR=tmp_project_root / "data",
           MODEL_DIR=tmp_project_root / "models",
       ))
       return config.config

   @pytest.fixture
   def sample_features_df():
       """Return sample features DataFrame for testing."""
       import pandas as pd
       from constants import LITE_MODEL_FEATURES

       data = {feat: [0.5] for feat in LITE_MODEL_FEATURES}
       return pd.DataFrame(data)

   @pytest.fixture
   def api_client():
       """Return FastAPI test client."""
       from fastapi.testclient import TestClient
       from api.app import app
       return TestClient(app)
   ```

3. Update `requirements-dev.in` to include testing dependencies:

   ```
   -r requirements.in

   pytest==7.4.3
   pytest-cov==4.1.0
   pytest-mock==3.12.0
   httpx==0.25.2
   ```

### Phase 4.1: Unit Tests

**Actions**

1. `tests/unit/test_odds.py`:

   ```python
   import pytest
   from services.odds_engine import american_to_payout, american_to_implied_prob, compute_ev

   def test_american_to_payout_positive():
       payout = american_to_payout(100)
       assert payout == 1.0

   def test_american_to_payout_negative():
       payout = american_to_payout(-110)
       assert abs(payout - 0.909) < 0.01

   def test_american_to_implied_prob():
       prob = american_to_implied_prob(-110)
       assert abs(prob - 0.524) < 0.01

   def test_compute_ev_positive():
       ev = compute_ev(prob_win=0.6, odds=-110)
       assert ev > 0

   def test_compute_ev_negative():
       ev = compute_ev(prob_win=0.4, odds=-110)
       assert ev < 0
   ```

2. `tests/unit/test_validators.py`:

   ```python
   import pytest
   import pandas as pd
   from validators import validate_features
   from errors import ValidationError

   def test_validate_features_missing_column():
       df = pd.DataFrame({"col1": [1]})
       with pytest.raises(ValidationError, match="Missing"):
           validate_features(df, ["col1", "col2"])

   def test_validate_features_nan():
       df = pd.DataFrame({"col1": [1], "col2": [None]})
       with pytest.raises(ValidationError, match="NaN"):
           validate_features(df, ["col1", "col2"])

   def test_validate_features_ok():
       df = pd.DataFrame({"col1": [1], "col2": [2]})
       validate_features(df, ["col1", "col2"])  # Should not raise
   ```

3. `tests/unit/test_config.py`:
   ```python
   def test_config_from_env(monkeypatch):
       monkeypatch.setenv("UFC_DATA_DIR", "/tmp/data")
       from config import Config
       cfg = Config()
       assert str(cfg.DATA_DIR) == "/tmp/data"
   ```

### Phase 4.2: Integration Tests

**Actions**

1. `tests/integration/test_predictor_service.py`:

   ```python
   import pytest
   import pandas as pd
   from services.predictor import PredictionService
   from constants import LITE_MODEL_FEATURES

   @pytest.mark.integration
   def test_predictor_inference(sample_features_df, mock_config):
       """Test end-to-end prediction with sample features."""
       predictor = PredictionService()
       probs = predictor.predict(sample_features_df)
       assert len(probs) == len(sample_features_df)
       assert all(0 <= p <= 1 for p in probs)
   ```

2. `tests/integration/test_api_endpoints.py`:

   ```python
   import pytest
   from fastapi.testclient import TestClient
   from api.app import app

   @pytest.mark.integration
   def test_health_check(api_client):
       response = api_client.get("/health")
       assert response.status_code == 200
       assert response.json()["status"] == "ok"

   @pytest.mark.integration
   def test_predict_endpoint(api_client, sample_features_df):
       payload = {
           "fights": sample_features_df.to_dict(orient="records"),
           "model_version": "lite"
       }
       response = api_client.post("/api/predict", json=payload)
       assert response.status_code == 200
       assert len(response.json()) > 0

   @pytest.mark.integration
   def test_scrape_job_unauthorized(api_client):
       response = api_client.post("/api/jobs/scrape", json={})
       assert response.status_code == 401

   @pytest.mark.integration
   def test_scrape_job_authorized(api_client, monkeypatch):
       monkeypatch.setenv("ADMIN_API_KEY", "test-key")
       headers = {"Authorization": "Bearer test-key"}
       response = api_client.post("/api/jobs/scrape", json={}, headers=headers)
       assert response.status_code == 202
       assert "job_id" in response.json()
   ```

### Phase 4.3: ML Regression Tests

**Actions**

1. `tests/ml/test_prediction_determinism.py`:

   ```python
   import json
   import pytest
   from pathlib import Path
   from services.predictor import PredictionService

   @pytest.mark.ml
   def test_prediction_determinism():
       """Verify predictions on fixed input produce stable results."""
       predictor = PredictionService()

       # Load fixed test fixture
       fixture_path = Path(__file__).parent / "fixtures" / "sample_features.csv"
       import pandas as pd
       df = pd.read_csv(fixture_path)

       # Run prediction multiple times
       results = []
       for _ in range(3):
           probs = predictor.predict(df)
           results.append(probs)

       # Assert all runs produce identical results
       for i in range(1, len(results)):
           for j in range(len(results[0])):
               assert abs(results[0][j] - results[i][j]) < 1e-6

   @pytest.mark.ml
   def test_prediction_against_golden_file():
       """Compare predictions against locked golden file."""
       predictor = PredictionService()

       fixture_path = Path(__file__).parent / "fixtures" / "sample_features.csv"
       golden_path = Path(__file__).parent / "fixtures" / "sample_predictions.json"

       import pandas as pd
       df = pd.read_csv(fixture_path)
       probs = predictor.predict(df)

       with open(golden_path) as f:
           golden = json.load(f)

       for i, (predicted, expected) in enumerate(zip(probs, golden["probabilities"])):
           assert abs(predicted - expected) < 0.001, f"Prediction {i} diverged"
   ```

2. `tests/ml/test_training_metrics.py`:

   ```python
   import pytest
   from services.trainer import ModelTrainer

   @pytest.mark.ml
   def test_training_metrics_floor():
       """Ensure training achieves minimum acceptable metrics."""
       trainer = ModelTrainer()

       # Train on sample data
       metadata = trainer.train("data/ufc_features.csv")

       # Check floors
       assert metadata["metrics"]["roc_auc"] >= 0.60, "ROC-AUC below minimum floor"
       assert metadata["metrics"]["log_loss"] <= 0.5, "Log loss above maximum floor"
   ```

### Phase 4.4: CI Pipeline

**Actions**

1. Create `.github/workflows/test.yml`:

   ```yaml
   name: Tests

   on:
     push:
       branches: [main, develop]
     pull_request:
       branches: [main, develop]

   jobs:
     test:
       runs-on: ubuntu-latest
       services:
         postgres:
           image: postgres:15
           env:
             POSTGRES_PASSWORD: postgres
           options: >-
             --health-cmd pg_isready
             --health-interval 10s
             --health-timeout 5s
             --health-retries 5
           ports:
             - 5432:5432

       steps:
         - uses: actions/checkout@v4

         - name: Set up Python 3.12
           uses: actions/setup-python@v4
           with:
             python-version: "3.12"

         - name: Install dependencies
           run: |
             pip install -r requirements-dev.txt

         - name: Lint with flake8
           run: |
             flake8 src --count --max-line-length=100 --exit-zero

         - name: Type check with mypy
           run: |
             mypy src --ignore-missing-imports

         - name: Format check with black
           run: |
             black --check src

         - name: Test with pytest
           env:
             DATABASE_URL: postgresql://postgres:postgres@localhost/ufc_ml_test
           run: |
             pytest tests --cov=src --cov-report=xml

         - name: Upload coverage to Codecov
           uses: codecov/codecov-action@v3
   ```

2. Create `pyproject.toml` for tool config:

   ```toml
   [tool.pytest.ini_options]
   minversion = "7.0"
   addopts = "-ra -q --strict-markers"
   markers = [
       "unit: unit tests",
       "integration: integration tests",
       "ml: ML-specific tests",
   ]
   testpaths = ["tests"]

   [tool.black]
   line-length = 100

   [tool.mypy]
   python_version = "3.12"
   warn_return_any = true
   warn_unused_configs = true
   ```

**Files Created**

- Create: `tests/` directory and all test files.
- Create: `.github/workflows/test.yml`.
- Update: `requirements-dev.in`, `pyproject.toml`.

---

**Phase 4 Verification**

- [ ] All tests pass locally: `pytest`.
- [ ] Test coverage > 80% for core services: `pytest --cov=src`.
- [ ] CI pipeline runs on PR.
- [ ] Prediction determinism verified against golden files.
- [ ] Training metrics exceeds floors on sample data.

---

## Phase 5: React + TypeScript Frontend

**Goal**: Build internal-ops console with prediction runner, model status page, and job control UI.

**Deliverables**

### Phase 5.0: Frontend Project Setup

**Actions**

1. Initialize React + TypeScript with Vite:

   ```bash
   npm create vite@latest ufc-ml-frontend -- --template react-ts
   cd ufc-ml-frontend
   npm install
   ```

2. Add dependencies:

   ```bash
   npm install \
     react-query \
     axios \
     zod \
     react-hook-form \
     @hookform/resolvers \
     react-router-dom \
     lucide-react \
     clsx \
     date-fns
   ```

3. Project structure:
   ```
   frontend/
   ├── src/
   │   ├── api/
   │   │   ├── client.ts
   │   │   ├── types.ts
   │   │   └── queries.ts
   │   ├── features/
   │   │   ├── predict/
   │   │   │   ├── components/
   │   │   │   │   ├── PredictionForm.tsx
   │   │   │   │   └── PredictionResultsTable.tsx
   │   │   │   ├── hooks/
   │   │   │   │   └── usePredictionForm.ts
   │   │   │   └── PredictPage.tsx
   │   │   ├── model/
   │   │   │   ├── components/
   │   │   │   │   ├── ModelInfo.tsx
   │   │   │   │   └── FeatureImportanceChart.tsx
   │   │   │   └── ModelPage.tsx
   │   │   ├── jobs/
   │   │   │   ├── components/
   │   │   │   │   ├── JobMonitor.tsx
   │   │   │   │   ├── ScrapeJobForm.tsx
   │   │   │   │   └── JobStatusPoll.tsx
   │   │   │   ├── hooks/
   │   │   │   │   └── useJobPoll.ts
   │   │   │   └── JobsPage.tsx
   │   │   └── layout/
   │   │       ├── components/
   │   │       │   ├── Header.tsx
   │   │       │   ├── Sidebar.tsx
   │   │       │   └── Layout.tsx
   │   │       └── LayoutPage.tsx
   │   ├── App.tsx
   │   ├── main.tsx
   │   └── index.css
   ├── vite.config.ts
   ├── tsconfig.json
   ├── package.json
   └── .env.example
   ```

### Phase 5.1: API Client & Types

**Actions**

1. `frontend/src/api/types.ts`:

   ```typescript
   export interface FightFeatures {
     is_title_bout: number;
     total_rounds: number;
     age_diff: number;
     height_diff: number;
     reach_diff: number;
     SLpM_total_diff: number;
     SApM_total_diff: number;
     sig_str_acc_total_diff: number;
     str_def_total_diff: number;
     td_avg_diff: number;
     td_acc_total_diff: number;
     td_def_total_diff: number;
     sub_avg_diff: number;
     wins_total_diff: number;
     losses_total_diff: number;
   }

   export interface PredictionResult {
     red_fighter: string;
     blue_fighter: string;
     prob_red_win: number;
     prob_blue_win: number;
     model_version: string;
   }

   export interface ModelInfo {
     model_type: string;
     n_estimators: number;
     n_features: number;
     features: string[];
     last_trained: string;
     metrics: {
       roc_auc: number;
       log_loss: number;
     };
   }

   export enum JobStatus {
     Queued = "queued",
     Running = "running",
     Completed = "completed",
     Failed = "failed",
   }

   export interface Job {
     job_id: string;
     status: JobStatus;
     created_at: string;
     updated_at?: string;
     progress?: Record<string, any>;
     result?: Record<string, any>;
     error?: string;
   }
   ```

2. `frontend/src/api/client.ts`:

   ```typescript
   import axios, { AxiosInstance } from "axios";
   import { PredictionResult, ModelInfo, Job } from "./types";

   class APIClient {
     private client: AxiosInstance;
     private apiKey: string;

     constructor(baseURL: string, apiKey: string) {
       this.apiKey = apiKey;
       this.client = axios.create({ baseURL });
       this.client.interceptors.request.use((config) => {
         config.headers.Authorization = `Bearer ${apiKey}`;
         return config;
       });
     }

     async predict(
       features: Record<string, any>[],
     ): Promise<PredictionResult[]> {
       const { data } = await this.client.post("/api/predict", {
         fights: features,
         model_version: "lite",
       });
       return data;
     }

     async modelInfo(): Promise<ModelInfo> {
       const { data } = await this.client.get("/api/model-info");
       return data;
     }

     async scrapeJob(payload: Record<string, any>): Promise<Job> {
       const { data } = await this.client.post("/api/jobs/scrape", payload);
       return data;
     }

     async trainJob(): Promise<Job> {
       const { data } = await this.client.post("/api/jobs/train", {});
       return data;
     }

     async getJob(jobId: string): Promise<Job> {
       const { data } = await this.client.get(`/api/jobs/${jobId}`);
       return data;
     }
   }

   export default new APIClient(
     import.meta.env.VITE_API_URL || "http://localhost:8000",
     import.meta.env.VITE_ADMIN_API_KEY || "",
   );
   ```

3. `frontend/src/api/queries.ts` (React Query hooks):

   ```typescript
   import {
     useQuery,
     useMutation,
     useQueryClient,
   } from "@tanstack/react-query";
   import client from "./client";
   import { PredictionResult, ModelInfo, Job } from "./types";

   export const useModelInfo = () =>
     useQuery({
       queryKey: ["model-info"],
       queryFn: () => client.modelInfo(),
       staleTime: 5 * 60 * 1000, // 5 min cache
     });

   export const usePredictMutation = () =>
     useMutation({
       mutationFn: (features: Record<string, any>[]) =>
         client.predict(features),
     });

   export const useScrapeJobMutation = () =>
     useMutation({
       mutationFn: (payload: Record<string, any>) => client.scrapeJob(payload),
     });

   export const useTrainJobMutation = () =>
     useMutation({
       mutationFn: () => client.trainJob(),
     });

   export const useJobStatus = (jobId: string, enabled: boolean = false) =>
     useQuery({
       queryKey: ["job", jobId],
       queryFn: () => client.getJob(jobId),
       enabled,
       refetchInterval: (data) =>
         data?.status === "completed" || data?.status === "failed"
           ? false
           : 2000,
     });
   ```

### Phase 5.2: Page Components

**Actions**

1. `frontend/src/features/predict/PredictPage.tsx`:

   ```typescript
   import React, { useState } from "react";
   import { usePredictMutation, useModelInfo } from "@/api/queries";
   import PredictionForm from "./components/PredictionForm";
   import PredictionResultsTable from "./components/PredictionResultsTable";

   export default function PredictPage() {
     const [results, setResults] = useState([]);
     const { data: modelInfo } = useModelInfo();
     const { mutate: predict, isLoading, error } = usePredictMutation();

     const handleSubmit = async (features: Record<string, any>[]) => {
       predict(features, {
         onSuccess: (data) => setResults(data),
       });
     };

     return (
       <div className="container mx-auto p-4">
         <h1 className="text-3xl font-bold mb-4">Prediction Runner</h1>
         {modelInfo && (
           <div className="mb-4 p-2 bg-blue-100 rounded">
             Model: {modelInfo.model_type} | Last trained: {modelInfo.last_trained} | ROC-AUC:{" "}
             {modelInfo.metrics.roc_auc.toFixed(3)}
           </div>
         )}
         <PredictionForm onSubmit={handleSubmit} loading={isLoading} error={error} />
         {results.length > 0 && <PredictionResultsTable results={results} />}
       </div>
     );
   }
   ```

2. `frontend/src/features/jobs/JobsPage.tsx`:

   ```typescript
   import React, { useState } from "react";
   import { useScrapeJobMutation, useTrainJobMutation, useJobStatus } from "@/api/queries";
   import ScrapeJobForm from "./components/ScrapeJobForm";
   import JobStatusPoll from "./components/JobStatusPoll";

   export default function JobsPage() {
     const [activeJobId, setActiveJobId] = useState<string | null>(null);
     const { mutate: scrape, isPending: scrapeLoading } = useScrapeJobMutation();
     const { mutate: train, isPending: trainLoading } = useTrainJobMutation();
     const { data: jobStatus } = useJobStatus(activeJobId ?? "", !!activeJobId);

     const handleScrapeSubmit = async (payload: Record<string, any>) => {
       scrape(payload, {
         onSuccess: (data) => setActiveJobId(data.job_id),
       });
     };

     const handleTrain = async () => {
       train(
         {},
         {
           onSuccess: (data) => setActiveJobId(data.job_id),
         }
       );
     };

     return (
       <div className="container mx-auto p-4">
         <h1 className="text-3xl font-bold mb-4">Jobs & Operations</h1>
         <div className="grid grid-cols-2 gap-4">
           <ScrapeJobForm onSubmit={handleScrapeSubmit} loading={scrapeLoading} />
           <button onClick={handleTrain} disabled={trainLoading} className="p-4 bg-green-500">
             {trainLoading ? "Training..." : "Train Model"}
           </button>
         </div>
         {activeJobId && jobStatus && <JobStatusPoll job={jobStatus} />}
       </div>
     );
   }
   ```

### Phase 5.3: Routing & Main App

**Actions**

1. `frontend/src/App.tsx`:

   ```typescript
   import React from "react";
   import { BrowserRouter, Routes, Route } from "react-router-dom";
   import Layout from "./features/layout/components/Layout";
   import PredictPage from "./features/predict/PredictPage";
   import ModelPage from "./features/model/ModelPage";
   import JobsPage from "./features/jobs/JobsPage";

   export default function App() {
     return (
       <BrowserRouter>
         <Layout>
           <Routes>
             <Route path="/" element={<PredictPage />} />
             <Route path="/model" element={<ModelPage />} />
             <Route path="/jobs" element={<JobsPage />} />
           </Routes>
         </Layout>
       </BrowserRouter>
     );
   }
   ```

2. `frontend/vite.config.ts`:

   ```typescript
   import { defineConfig } from "vite";
   import react from "@vitejs/plugin-react";
   import path from "path";

   export default defineConfig({
     plugins: [react()],
     resolve: {
       alias: {
         "@": path.resolve(__dirname, "./src"),
       },
     },
     server: {
       proxy: {
         "/api": "http://localhost:8000",
       },
     },
   });
   ```

**Files Created**

- Create: `frontend/` directory with all components, pages, and utilities.
- Create: `.env.example` with `VITE_API_URL`, `VITE_ADMIN_API_KEY`.

---

**Phase 5 Verification**

- [ ] Frontend starts without errors: `npm run dev`.
- [ ] Prediction form submits to backend and displays results.
- [ ] Model info page shows current metrics and features.
- [ ] Job control page queues scrape/train jobs and polls status.
- [ ] Layout navigation works across all pages.
- [ ] Error handling and loading states display correctly.

---

## Phase 6: CI/CD & Production Deployment

**Goal**: Establish testing pipeline, container builds, environment promotion, and observability.

**Deliverables**

### Phase 6.0: GitHub Actions CI

**Create `.github/workflows/build.yml`**:

```yaml
name: Build & Release

on:
  push:
    tags:
      - "v*"

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v2

      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v2
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push backend image
        uses: docker/build-push-action@v4
        with:
          context: .
          target: runtime
          push: true
          tags: ghcr.io/${{ github.repository }}/backend:${{ github.ref_name }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Build frontend
        run: |
          cd frontend
          npm install
          npm run build

      - name: Push frontend to registry
        uses: docker/build-push-action@v4
        with:
          context: ./frontend
          push: true
          tags: ghcr.io/${{ github.repository }}/frontend:${{ github.ref_name }}
```

### Phase 6.1: Environment & Docker Compose

**Create `.env.production`**:

```env
DATABASE_URL=postgresql://user:pass@neon-prod-endpoint/ufc_ml
REDIS_URL=redis://redis-prod:6379
ADMIN_API_KEY=<secure-key>
LOG_LEVEL=INFO
VITE_API_URL=https://api.ufc-ml.example.com
```

**Update `docker-compose.yml` for production profile**:

```yaml
version: "3.9"
services:
  api:
    # ... existing config ...
    profiles: ["prod"]
    restart: always
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/ready"]
      interval: 30s
      timeout: 5s
      retries: 3
    environment:
      DATABASE_URL: ${DATABASE_URL}
      ADMIN_API_KEY: ${ADMIN_API_KEY}

  worker:
    profiles: ["prod"]
    restart: always
    # ...

  frontend:
    build:
      context: ./frontend
    ports:
      - "80:3000"
    environment:
      VITE_API_URL: "https://api.ufc-ml.example.com"
    profiles: ["prod"]
    restart: always
```

### Phase 6.2: Database Backups & Monitoring

**Create backup script `scripts/backup-neon.sh`**:

```bash
#!/bin/bash
DATABASE_URL=${1:-$DATABASE_URL}
BACKUP_DIR=${2:-./backups}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

pg_dump "$DATABASE_URL" | gzip > "$BACKUP_DIR/ufc_ml_$TIMESTAMP.sql.gz"
echo "Backup complete: ufc_ml_$TIMESTAMP.sql.gz"

# Retention: keep last 30 days
find "$BACKUP_DIR" -name "ufc_ml_*.sql.gz" -mtime +30 -delete
```

**Create monitoring/alerting integration** (Prometheus + Grafana or cloud provider's monitoring):

```python
# src/monitoring.py
from prometheus_client import Counter, Histogram, start_http_server

prediction_counter = Counter("predictions_total", "Total predictions")
job_duration = Histogram("job_duration_seconds", "Job execution time")

@app.post("/api/predict")
async def predict_fights(req):
    prediction_counter.inc()
    with job_duration.time():
        # ... prediction logic
```

### Phase 6.3: Deployment Strategies

**Option A: Docker Compose on single VM** (simplest for MVP):

```bash
# Pull latest images, run migrations, restart services
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose.prod.yml up -d
```

**Option B: Kubernetes** (for scaling):

```yaml
# k8s/api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ufc-ml-api
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: api
          image: ghcr.io/ruckiryan/ufc-ml/backend:v1.0
          ports:
            - containerPort: 8000
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: ufc-secrets
                  key: database-url
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
```

**Files Created/Updated**

- Create: `.github/workflows/build.yml`, `.env.production`, `scripts/backup-neon.sh`, `src/monitoring.py`.
- Update: `docker-compose.yml`.

---

### Phase 6.4: Runbook & Playbooks

**Create `docs/OPERATIONS.md`**:

- How to deploy a new version.
- How to troubleshoot common issues.
- How to scale workers or API replicas.
- Backup and restore procedures.
- Incident response for model failures, data corruption, etc.

**Phase 6 Verification**

- [ ] CI pipeline runs tests on every PR.
- [ ] Build workflow publishes container images to registry on tag.
- [ ] Docker Compose production config starts without manual intervention.
- [ ] Database migrations apply to NeonDB in staging.
- [ ] Health checks pass for all services.
- [ ] Backups run on schedule and older backups are purged.

---

## Phase 7: Post-MVP Expansion (Future)

**Out of scope for initial release; prioritize based on user feedback:**

1. **Public Read-Only Prediction Surface**
   - Unauthenticated `GET /api/public/predictions?event=ufc325` endpoints.
   - Public frontend showing recent predictions and battle-tested historical accuracy.

2. **Richer Analytics & Backtests**
   - Historical prediction accuracy dashboard.
   - Backtest UI: select date range, compare predicted vs. actual outcomes.
   - Feature impact analysis: which stats drove each prediction?

3. **Model Experimentation & A/B Testing**
   - Admin endpoint to queue training with custom hyperparams.
   - Route prediction traffic by model version for A/B testing.
   - Side-by-side comparison of model variants.

4. **Odds Aggregation Service**
   - Sync live odds from multiple sportsbooks periodically.
   - Auto-alert when EV exceeds threshold across fights.

5. **Advanced Orchestration**
   - Migrate to Airflow if multi-step DAG complexity grows.
   - Enhanced retry/backoff policies and failure notifications.

6. **Scalability Hardening**
   - Kubernetes deployment with HPA.
   - Database read replicas for analytics queries.
   - Model inference caching (Redis).
   - CDN for frontend assets.

---

## Implementation Checklist

Use this checklist to track progress across all phases:

- [ ] **Phase 0**: Architecture contracts finalized and documented.
- [ ] **Phase 1**: Config centralization, logging, error handling, service modules complete.
- [ ] **Phase 1.5**: Scraper resilience and incremental mode working.
- [ ] **Phase 2**: FastAPI backend with sync/async endpoints deployed and tested.
- [ ] **Phase 3**: Scheduler integrated; recurring jobs (scrape, train) working.
- [ ] **Phase 4**: Test suite with unit, integration, and ML tests passing; CI pipeline green.
- [ ] **Phase 5**: React frontend built; routes working; API integration tested.
- [ ] **Phase 6**: CI/CD pipeline publishing images; production Docker Compose working.
- [ ] **Staging Validation**: All workflows tested in staging environment.
- [ ] **Production Deployment**: API and frontend live; monitoring and backups in place.

---

## Timeline Estimate

**Rough effort estimate** (person-weeks; assumes 1 full-time developer):

| Phase                     | Tasks                                                      | Effort          |
| ------------------------- | ---------------------------------------------------------- | --------------- |
| **0**                     | Architecture & contracts                                   | 0.5–1           |
| **1**                     | Pipeline hardening (config, logging, services, validation) | 2–3             |
| **1.5**                   | Scraper resilience                                         | 0.5–1           |
| **2**                     | FastAPI backend + async jobs                               | 3–4             |
| **3**                     | Scheduling & orchestration                                 | 1–1.5           |
| **4**                     | Testing strategy & CI                                      | 2–3             |
| **5**                     | React frontend                                             | 3–4             |
| **6**                     | CI/CD & deployment                                         | 1–2             |
| **Validation & bugfixes** | UAT, performance tuning                                    | 2–3             |
| **Total**                 |                                                            | **16–23 weeks** |

**Parallelization opportunities**:

- Phases 1 and 2 can overlap (start frontend scaffolding while backend hardens).
- Phase 4 (tests) can begin during Phase 2 (API endpoints).
- Phase 5 (frontend) can begin once Phase 2 API contracts are stable.

---

## Recommended Kickoff Sequence

1. **Week 1**: Finalize Phase 0 architecture in team sync; create design doc and get buy-in.
2. **Week 2–3**: Execute Phase 1 refactoring in parallel: config/logging + service modules + validators.
3. **Week 4**: Phase 1.5 scraper hardening.
4. **Week 5–7**: Phase 2 API + worker infrastructure.
5. **Week 3–7 (parallel)**: Phase 4 testing framework and CI setup.
6. **Week 8–10**: Phase 5 React frontend development.
7. **Week 11**: Phase 3 scheduling integration.
8. **Week 12**: Phase 6 CI/CD and production deployment.
9. **Week 13**: Staging validation, performance testing, bugfixes.
10. **Week 14**: Production deployment and monitoring handoff.

---

## Key Success Metrics

- **Availability**: API uptime ≥ 99% after production launch.
- **Latency**: Prediction endpoints < 500ms p95.
- **Data freshness**: Scraper completes daily; data lag < 24 hours post-event.
- **Model accuracy**: ROC-AUC on holdout test ≥ 0.75; training succeeds ≥ 95% of manual runs.
- **Observability**: 100% of errors logged and traceable; alerting fires < 5 min post-failure.
- **Testing**: > 80% code coverage; all CI checks pass on main.
- **User adoption**: Team uses internal ops console daily for predictions/job monitoring.

---

## Questions & Risks

**Frequently Asked**

1. **Should I start with Phase 0 architecture discussions or jump to code?**
   - Do Phase 0 first. Misaligned service boundaries will cause pain later. 30 min team sync on contracts is worth weeks of rework.

2. **Can I skip testing (Phase 4)?**
   - Not recommended. ML models are easy to break quietly. Regression tests and API contract tests catch 80% of issues before production.

3. **Should I use Celery or APScheduler?**
   - Start with APScheduler (Phase 3) for simplicity. Migrate to Celery if job volume or complexity grows (Phase 7).

4. **What if NeonDB isn't ready when I'm building backend?**
   - Use SQLite locally (Phase 2). Swap DATABASE_URL to NeonDB once available; SQLAlchemy abstracts the difference.

5. **Is the frontend scope (Phase 5) too large?**
   - Yes. If time is tight, ship Phase 5 as a minimal CLI tool or Jupyter notebook until Phase 5 is ready. The backend (Phase 2) is the critical path.

**Risks**

| Risk                                              | Mitigation                                                                                          |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Scraper breaks if UFC Stats changes CSS           | Add selector versioning in Phase 1.5; set up monitoring for HTTP 404s from scraper.                 |
| Model performance degrades over time (data drift) | Add monitoring dashboard (Phase 6) to track metrics; implement drift detection in retraining logic. |
| API gets overloaded by bulk prediction requests   | Set rate limits; queue long-running bulk jobs (Phase 2 async design handles this).                  |
| Database migrations fail in production            | Test migrations in staging first (Phase 6). Keep rollback scripts ready.                            |
| Frontend breaks on backend API changes            | Use API versioning in Phase 2 (e.g., `/api/v1/predict`). Frontend points to stable contract.        |

---

## Document History

- **2026-03-20**: Initial roadmap created based on codebase audit and team requirements.
