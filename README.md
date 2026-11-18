# Open ML Studio v3 — Hybrid ML Workbench

A local-first general-purpose tabular machine-learning workbench with a browser frontend and Python/FastAPI + scikit-learn backend.

## Project bundle

The complete runnable source package is included in [`Open_ML_Studio_v3_Hybrid.zip`](./Open_ML_Studio_v3_Hybrid.zip). Extract it and follow the bundled `README.md` for setup.

## Architecture

- Frontend: responsive HTML/CSS/JavaScript workspace
- Backend: Python + FastAPI
- ML engine: scikit-learn pipelines
- Tasks: classification and regression
- Algorithms: logistic/ridge, random forest, extra trees, gradient boosting, histogram gradient boosting, decision tree and k-nearest neighbours
- Evaluation: held-out metrics and permutation feature importance

## Quick start

1. Download and extract `Open_ML_Studio_v3_Hybrid.zip`.
2. Install Python 3.10–3.12.
3. On Windows, run `run_windows.bat`; on macOS/Linux, run `./run_mac_linux.sh`.
4. Open `frontend/index.html` in a modern browser.
5. API docs: `http://127.0.0.1:8000/docs`.

## Important

This is an early v3 foundation, not a production-hosted service. It currently has no authentication or multi-user isolation. Do not expose the API directly to the public internet. See the bundled README for limitations and the roadmap.
