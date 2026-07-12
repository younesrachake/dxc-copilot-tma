-- PostgreSQL first-boot initialization.
--
-- The application schema is owned by Alembic (backend/migrations/) and is
-- applied by the backend entrypoint on startup — do NOT create application
-- tables here. This file previously defined a divergent legacy schema (UUID
-- primary keys) that conflicted with the SQLAlchemy models and would have
-- broken a fresh production deployment. It now only installs extensions that
-- require superuser privileges.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
