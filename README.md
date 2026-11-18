# Open ML Studio v3.1 — Secure Cloud ML Workbench

A mobile-friendly browser UI served by Python FastAPI and scikit-learn for general-purpose tabular machine learning. The frontend and API are served from the same origin, and API actions require a shared access password.

## Requirements
- Python 3.10–3.12 recommended
- Internet access during first dependency installation
- Modern Chrome, Edge or Firefox
- 8 GB RAM recommended for larger datasets

## Windows
1. Extract the ZIP.
2. Install Python 3.10–3.12 and enable Add Python to PATH.
3. Double-click `run_windows.bat`.
4. Wait until Uvicorn reports that it is running on `http://127.0.0.1:8000`.
5. Open `frontend/index.html` in a browser. The engine indicator should show Connected.
6. API documentation: `http://127.0.0.1:8000/docs`.

## macOS / Linux
Run `chmod +x run_mac_linux.sh && ./run_mac_linux.sh`, then open `frontend/index.html`.

## Included algorithms
Classification: logistic regression, random forest, extra trees, gradient boosting, histogram gradient boosting, decision tree and k-nearest neighbours.

Regression: ridge, random forest, extra trees, gradient boosting, histogram gradient boosting, decision tree and k-nearest neighbours.

Pipelines perform numeric median imputation + scaling and categorical most-frequent imputation + one-hot encoding. Evaluation uses a held-out test set and reports classification or regression metrics. Permutation importance is computed against held-out data.

## Important limitations in v3.0
This is a functional starter release, not yet a production AutoML suite. Dataset and live model registries are in memory and clear on API restart; experiment JSON and joblib files persist. Model metadata is not reloaded after restart. Cross-validation, SHAP, neural networks, XGBoost/LightGBM, hyperparameter optimisation, grouped/time-series splitters, drift monitoring, authentication and multi-user isolation are not implemented yet. Chronological split follows row order; sort your CSV by timestamp first. Permutation importance is not causal explanation.

Do not expose this API to the public internet. It has no authentication. Only load trusted joblib files. For trading research, use walk-forward validation, fees, slippage, realistic execution and paper trading; a high historical score does not establish future profitability.

## API endpoints
`GET /api/health`; `POST /api/datasets`; `GET /api/datasets/{id}`; `POST /api/train`; `POST /api/predict`; `GET /api/experiments`; `GET /api/models`.

## Deploy on Render

Create a **Web Service** from this public GitHub repository.

- Runtime: Python 3
- Branch: `main`
- Root Directory: leave blank
- Build Command: `pip install -r backend/requirements.txt`
- Start Command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- Instance: Free is suitable only for an initial low-volume test; model training may exceed its memory/CPU limits.

Before deploying, add an environment variable:
- Key: `APP_PASSWORD`
- Value: generate a long, unique secret (at least 24 random characters). Keep it private and do not commit it to GitHub.

Open the service URL after deployment. The browser UI is served at `/`. The first protected action asks for the shared access password; it is kept only in that browser tab's session storage. `GET /api/health` is public for the hosting health check.

**Security scope:** this is a single shared-password starter, not a multi-user service. Anyone with the password can access the same in-memory datasets and model registry. Do not upload confidential, personal, financial, medical, or otherwise sensitive datasets. Use only for controlled testing until individual accounts, tenant isolation, durable storage, rate limits, and a security review are implemented.
