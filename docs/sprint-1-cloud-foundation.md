# Sprint 1 — Cloud Foundation & Model Intelligence

**Status:** Supabase selected; foundation schema and typed configuration committed; live connection pending  
**Branch:** `sprint-1-cloud-foundation`  
**Goal:** Replace process-local registries with durable, tenant-aware persistence while preserving the existing FastAPI and scikit-learn engine.

## 1. Decisions and boundaries

- Deployment direction: cloud-backed.
- Selected platform: Supabase.
- Metadata store: Supabase-hosted PostgreSQL.
- Binary artifacts: private Supabase Storage bucket (`open-ml-artifacts`).
- Application code must depend on storage interfaces, not a specific vendor SDK.
- Keep the ML training and prediction pipeline independent from persistence.
- Use database migrations; never create production tables implicitly at application startup.
- No cloud credentials, buckets, database URLs, or secrets are committed to Git.
- The current shared-password middleware is not sufficient for multi-user production. Tenant isolation is a release gate, not a cosmetic follow-up.
- Provider-specific provisioning is intentionally blocked until the owner selects a provider and configures credentials.

## 2. Target architecture

```text
Browser UI
   |
   | HTTPS + authenticated session
   v
FastAPI application
   |-- Authentication / authorization
   |-- Dataset service
   |-- Experiment service
   |-- Model registry service
   |-- Existing ML engine (scikit-learn)
   |
   +---- PostgreSQL (metadata, ownership, relationships, status)
   |
   +---- Private object storage (CSV, joblib, reports)
```

### Responsibility split

**PostgreSQL stores**
- user identity reference and account status
- projects and membership/roles
- dataset metadata, checksum, object key, size, row/column counts
- experiment configuration, metrics, status, timestamps and dataset reference
- model family, task, version, metrics, artifact key and training experiment reference
- audit events and storage lifecycle state

**Object storage stores**
- original uploaded dataset bytes
- serialized model artifacts
- generated reports and optional analysis exports

Do not store large CSV or model binaries as database BLOBs by default. Store opaque object keys in PostgreSQL. Buckets/containers must be private; use short-lived signed URLs only when direct browser transfer is later implemented.

## 3. Logical data model

All tenant-owned records carry an `owner_user_id` and, where applicable, a `project_id`. Authorization must be checked server-side for every read, update, delete, download, prediction and training request.

### Tables

| Table | Important columns | Purpose |
|---|---|---|
| users | id, auth_subject, email, status, created_at | Local user reference mapped to a trusted identity provider |
| projects | id, owner_user_id, name, created_at | Workspace boundary |
| project_members | project_id, user_id, role, created_at | Future collaboration and role-based access |
| datasets | id, project_id, owner_user_id, filename, object_key, sha256, size_bytes, row_count, column_count, status, created_at | Dataset metadata and object pointer |
| experiments | id, project_id, dataset_id, owner_user_id, task, target, config_json, status, metrics_json, created_at, completed_at | Reproducible training/analysis runs |
| models | id, project_id, owner_user_id, name, task, created_at | Stable model identity |
| model_versions | id, model_id, experiment_id, version, artifact_key, metrics_json, feature_schema_json, library_versions_json, created_at, is_active | Immutable model version records |
| audit_events | id, project_id, actor_user_id, action, resource_type, resource_id, details_json, created_at | Security and operational traceability |

Use UUID primary keys. Add indexes for owner/project lookups, dataset-to-experiment lookups, model/version lookups and creation timestamps. Enforce uniqueness for (model_id, version), and appropriate foreign keys and deletion rules. Prefer soft-delete/status transitions for cloud objects so metadata and artifacts can be reconciled safely.

## 4. Backend package layout

Proposed incremental layout:

```text
backend/
  main.py
  advanced.py
  config.py
  db/
    base.py
    session.py
    models.py
    migrations/
  services/
    dataset_service.py
    experiment_service.py
    model_registry.py
  storage/
    interfaces.py
    local.py
    s3_compatible.py
  schemas/
    datasets.py
    experiments.py
    models.py
  tests/
    test_tenant_isolation.py
    test_dataset_persistence.py
    test_model_registry.py
```

The existing `main.py` routes should gradually delegate persistence operations to services. Avoid a large rewrite of the ML engine.

## 5. Storage contracts

Define small interfaces before adding a provider SDK:

- `ObjectStorage.put(key, stream, content_type) -> ObjectInfo`
- `ObjectStorage.open(key) -> readable stream`
- `ObjectStorage.delete(key)`
- `ObjectStorage.exists(key) -> bool`
- `DatasetRepository.create/get/list/delete`
- `ExperimentRepository.create/get/list/update_status`
- `ModelRepository.create_model/create_version/get_version/list_versions`

Object keys must be generated by the server, not accepted as arbitrary user paths. Suggested key shape:

`tenant/{owner_user_id}/projects/{project_id}/{resource_type}/{resource_id}/{filename}`

Never expose bucket credentials or permanent object URLs to the browser.

## 6. Dataset upload lifecycle

1. Authenticate the user and verify project membership.
2. Validate extension, content, size and row/column limits.
3. Stream the upload to a temporary/quarantine object key; avoid loading multiple copies of a large file into memory.
4. Compute SHA-256 while streaming.
5. Parse and profile the dataset using bounded resource limits.
6. Create the dataset metadata row with status `ready` only after successful object upload and validation.
7. On failure, mark the operation failed and clean up the temporary object.
8. On download, authorize against dataset ownership/project membership before issuing a short-lived signed URL or streaming through the API.

The current 100 MB upload limit can remain initially, but request-size limits, timeouts and memory use must be tested under Codespaces and the chosen host.

## 7. Experiment and model lifecycle

1. Create an experiment row with status `queued` or `running`.
2. Load the dataset through the authorized dataset service.
3. Train and evaluate with the existing ML pipeline.
4. Save the model artifact to private object storage.
5. Persist metrics, feature schema, configuration, random seed and package versions.
6. Mark the experiment complete only after artifact and metadata writes succeed.
7. Create a new immutable model version; never silently overwrite a prior version.
8. If a model artifact upload succeeds but the database write fails, record/reconcile the orphan object through a cleanup task.

A future job queue may move long training jobs out of the web request process. It is not required for the first persistence milestone.

## 8. API evolution

Keep existing endpoints working during migration where practical. Add project scoping and authenticated ownership checks before enabling multi-user access.

Proposed endpoints:
- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{project_id}/datasets`
- `POST /api/projects/{project_id}/datasets`
- `GET /api/datasets/{dataset_id}`
- `DELETE /api/datasets/{dataset_id}`
- `GET /api/projects/{project_id}/experiments`
- `GET /api/experiments/{experiment_id}`
- `GET /api/models`
- `GET /api/models/{model_id}/versions`
- `POST /api/models/{model_id}/versions/{version}/predict`

The existing `APP_PASSWORD` middleware can remain temporarily for private development only. Before public multi-user deployment, replace it with individual identity-provider authentication, secure sessions, CSRF protection where applicable, role checks, rate limits and tenant-isolation tests.

## 9. Sprint 1 implementation sequence

### S1.1 — Contracts and configuration
- Add typed settings for database URL, object-storage endpoint, bucket, region and credentials.
- Add startup validation that fails clearly when production cloud configuration is incomplete.
- Add storage/repository interfaces and a local development adapter.
- Keep secrets in environment variables or the host's secret manager.

### S1.2 — Database and migrations
- Add SQLAlchemy models and Alembic migrations.
- Add connection pooling, transaction boundaries and health checks.
- Create users/projects/datasets/experiments/models/model_versions/audit_events schema.
- Do not run destructive migrations automatically on app startup.

### S1.3 — Object storage
- Implement private object storage adapter after provider selection.
- Add upload, read, delete and existence operations.
- Add checksum verification and orphan cleanup strategy.
- Configure encryption at rest, TLS in transit, retention and backup policies.

### S1.4 — Persistent dataset registry
- Replace process-local dataset metadata with repository-backed records.
- Store original files in object storage.
- Load datasets on demand by authorized ID rather than relying on a process-local dictionary.
- Preserve current CSV profiling and analysis behaviour.

### S1.5 — Persistent experiment and model registry
- Persist experiment summaries and status.
- Save model artifacts to object storage.
- Persist immutable model versions and reproducibility metadata.
- Restore model metadata after API restart.

### S1.6 — Security and verification
- Add tenant-isolation tests using two independent users/projects.
- Test unauthorized dataset/model access, signed URL expiry, upload failure and database failure.
- Test restart recovery: upload, train, restart API, list history, load model and predict.
- Verify backups and restore procedure before production use.

## 10. Acceptance criteria

Sprint 1 is complete only when:

- Dataset metadata and source files survive an API restart.
- Experiment history survives an API restart.
- Model versions and model artifacts can be retrieved and used after restart.
- Every resource query is scoped to an authenticated user/project.
- A second user cannot enumerate, read, overwrite or delete another user's resources.
- Failed uploads/training jobs do not leave records falsely marked complete.
- No credentials or private data are committed to the repository.
- Automated tests cover persistence, authorization and recovery.
- A documented backup and restore test has succeeded.

## 11. Not included in Sprint 1

- AI chat assistant and LLM provider integration
- automatic retraining or model drift remediation
- distributed training / GPU orchestration
- billing and subscription management
- public self-service registration
- production multi-region deployment

These should follow only after persistence, identity and tenant isolation are dependable.

## 12. Supabase provider decision and current implementation

**Selected provider:** Supabase for Auth, PostgreSQL and private Storage.

Committed foundation files:
- `backend/config.py`: typed environment settings and Supabase configuration validation. It does not create a network connection at import time.
- `.env.example`: safe variable-name template with blank Supabase credentials.
- `supabase/migrations/0001_initial_schema.sql`: initial metadata schema, indexes, project-owner membership trigger, RLS policies and private artifact bucket definition.
- `backend/requirements.txt`: adds `pydantic-settings` for typed settings.

### Configuration
Copy `.env.example` to `.env` and set the values only in the private Codespaces secret/environment or local ignored file. Never commit `.env`. The Supabase service-role key is server-only and must never appear in browser JavaScript or frontend environment variables.

### Next implementation gates
1. Create a Supabase project and configure Auth providers / redirect URLs.
2. Review and apply the SQL migration in the Supabase SQL Editor.
3. Create the private Storage bucket and verify its policies in the dashboard.
4. Configure server-side secrets and database connection pooling.
5. Implement Supabase Auth token verification and derive the user ID from the verified token.
6. Implement repository and object-storage adapters, then migrate dataset upload/read paths.
7. Add two-user isolation, persistence-after-restart and backup/restore tests.

**Current state:** Supabase has been selected and the initial schema/configuration groundwork is in GitHub. No Supabase project has been provisioned or connected; no migration has been applied; no user login or cloud upload is active. The current shared-password application remains a private development prototype and must not receive sensitive client data or be exposed as a multi-user production service.
