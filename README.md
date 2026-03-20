# UFC Fight Outcome Prediction (Machine Learning Project)

This project uses logistic regression (Binary Classification) and ML to predict each fighter's (red/blue corner) probability of winning based on fighter attributes, statistics, and historical performance.

Currently, three UFC events (UFC322, UFCQatar, UFC324) have been trained and predicted. To view the model's results on these previous events please checkout the model's [outcomes](/OUTCOMES.md).

# Getting Started

> [!NOTE]
> The following section assumes access to standard UNIX tools like [`bash/zsh`](https://www.gnu.org/software/bash/) and [`git`](https://git-scm.com/).
> Windows users: use [Git Bash](https://git-scm.com/downloads) or [WSL](https://learn.microsoft.com/en-us/windows/wsl/install).

## Cloning the repository

```sh
# HTTPS:
git clone https://github.com/ruckiryan/UFC_ML.git

# SSH:
git clone git@github.com:ruckiryan/UFC_ML.git

cd UFC_ML
```

## Python version

Python 3.12.x is required (`.python-version` pins `3.12.12`). We recommend [pyenv](https://github.com/pyenv/pyenv) to manage versions:

```sh
pyenv install 3.12.12
pyenv local 3.12.12
python --version  # should print Python 3.12.x
```

## Creating a virtual environment

```sh
python -m venv .venv
source .venv/bin/activate       # Linux / macOS / WSL
# .venv\Scripts\activate        # Windows (cmd / PowerShell)
```

## Installing dependencies

Dependencies are managed with [pip-tools](https://pip-tools.readthedocs.io). There are two tiers:

| File | Purpose |
|---|---|
| `requirements.txt` | Core runtime — scraping, training, prediction |
| `requirements-dev.txt` | Adds Excel I/O (`openpyxl`), Jupyter notebooks, and visualisation |

**Core install** (scraper + model training + prediction scripts):

```sh
pip install -r requirements.txt
```

**Developer install** (also enables `clean_ufc_data.py` with `.xlsx` files and JupyterLab notebooks):

```sh
pip install -r requirements-dev.txt
```

### Regenerating locked dependencies

If you add a new dependency, edit the corresponding `.in` file and recompile:

```sh
pip install pip-tools          # only needed once, already in requirements-dev.txt

# Regenerate core
pip-compile --strip-extras --no-emit-trusted-host --no-header requirements.in -o requirements.txt

# Regenerate dev (includes core via -r requirements.in)
pip-compile --strip-extras --no-emit-trusted-host --no-header requirements-dev.in -o requirements-dev.txt

# Sync your environment to match the compiled output
pip-sync requirements-dev.txt  # or requirements.txt for a core-only env
```

> [!NOTE]
> Compiled `.txt` files include a `; sys_platform == "linux"` marker on CUDA packages pulled in by xgboost, so they install cleanly on Windows and macOS without modification.

## Running the pipeline

```sh
# 1. Scrape fight data from ufcstats.com
python -m src.scraper                  # all events  → data/raw_fights.csv
python -m src.scraper --max-events 5   # quick test

# 2. Clean data (requires dev install for openpyxl)
python src/clean_ufc_data.py           # data/large_dataset.xlsx → data/ufc_features.csv

# 3. Train
python src/train_lite_modelV2.py       # recommended → models/ufc_xgb_lite.joblib
python src/train_model.py              # full model   → models/ufc_xgb_model.joblib

# 4. Predict an upcoming event (copy an existing predict_*.py and adapt)
python src/predict_ufc325.py           # → data/ufc325_predictions.csv

# 5. Model analysis
python src/feature_importance.py       # → visuals/feature_importance.csv
python src/show_features.py            # print features in trained model
```
