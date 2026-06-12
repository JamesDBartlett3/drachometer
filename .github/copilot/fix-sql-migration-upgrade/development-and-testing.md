# Development and Testing Results: Fix SQL migration not performed during upgrade

## Overview
This feature fixes the issue where the SQL migration script (e.g. `001_migrate_to_model_dimension.sql`) was not automatically executed during an upgrade. The installer (`install.py`) has been modified to automatically track and apply SQL migrations before initializing the rest of the schema.

## Changes Made
1. **Added `apply_sql_migrations()` to `install.py`:**
   - Detects if `token_usage.db` exists.
   - If it exists, creates a `schema_migrations` table to track applied `.sql` migrations.
   - Intelligently detects if `001_migrate_to_model_dimension.sql` has already been implicitly applied (by checking for the existence of `model_id` in the `turns` table) and records it to avoid failing on subsequent upgrades.
   - Iterates over all `.sql` files in the `migrations/` directory and executes any that have not yet been recorded in the `schema_migrations` table.
2. **Updated `init_database()` in `install.py`:**
   - On a fresh database installation, creates the schema and immediately populates `schema_migrations` with all known migrations from the `migrations/` directory, preventing them from being falsely triggered in the future.
3. **Execution Ordering:**
   - `apply_sql_migrations()` is called inside `main()` right before `init_database()`. This ensures that existing legacy databases are cleanly upgraded using standard `.sql` migrations before any new additive columns are attempted by `init_database()`.

## Testing
We tested three major database scenarios:
1. **Legacy Database (pre-001 migration):**
   - Simulated a database lacking the `models` table and `model_id` in the `turns` table.
   - Verified that `apply_sql_migrations()` ran `001_migrate_to_model_dimension.sql`.
   - Result: The database was accurately updated to include the `models` table and populated based on existing textual model names, with the migration properly recorded in `schema_migrations`.
2. **Modern Database (already migrated implicitly):**
   - Simulated a database that already had `model_id` in the `turns` table but lacked a `schema_migrations` table.
   - Verified that the system safely detected the existence of `model_id`, inserted a record for `001_migrate_to_model_dimension.sql` into `schema_migrations`, and gracefully skipped re-executing the migration.
   - Result: Idempotency maintained, no `OperationalError` thrown.
3. **Fresh Database Installation:**
   - Deleted the local database entirely and ran `install.py`.
   - Verified that `init_database()` created the necessary tables and populated the `schema_migrations` table with the known `001_migrate_to_model_dimension.sql` migration.
   - Result: Ready for future migrations without incorrectly attempting to apply old ones.

Finally, we used the standard `python3 install.py` to ensure the internal smoke test completed successfully.
