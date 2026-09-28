-- =============================================================================
-- MiniBank — PostgreSQL init script
-- =============================================================================
-- Runs once on first container start (when the pgdata volume is empty).
-- Creates the two databases and their dedicated users.
--
-- The default 'postgres' superuser is only used for this bootstrapping step.
-- Each microservice connects with its own least-privilege user.
-- =============================================================================

-- IAM Service database and user
CREATE USER iam_user WITH PASSWORD 'iam_pass';
CREATE DATABASE iam_db OWNER iam_user;

-- Wallet/Ledger Service database and user
CREATE USER wallet_user WITH PASSWORD 'wallet_pass';
CREATE DATABASE wallet_db OWNER wallet_user;
