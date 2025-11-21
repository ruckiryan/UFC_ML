#  UFC Fight Outcome Prediction (Machine Learning Project)

This project uses logistic regression and ML to **predict each fighers (R/B) probability of winning** based on fighter attributes, statistics, and historical performance.  
It’s built with Python, trained locally in VS Code, and will later be deployed using **Google Vertex AI**.

---

##  Folder Structure
| Folder | Description |
|---------|-------------|
| `data/` | Raw and cleaned datasets (CSV files) |
| `notebooks/` | Jupyter notebooks for large ufc csv (Exploratory data anlysis) |
| `src/` | Python scripts for feature engineering, training, and predictions |
| `models/` | Saved trained model files (`.joblib` or `.pkl`) |
| `visuals/` | Plots and charts generated during analysis |
| `logs/` | Training logs and performance metrics |

---

##  Tech Requirements
- **Language:** Python 3.12  
- **Libraries:** `pandas`, `numpy`, `scikit-learn`, `xgboost`, `matplotlib`, `seaborn`, `joblib`, `jupyterlab`  
- **Tools:** VS Code

---

##  Getting Started

### 1. Activate the environment
```bash
.\.venv\Scripts\Activate.ps1
