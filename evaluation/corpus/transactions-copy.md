# AtlasDB transaction guide

AtlasDB is a fictional service used only for evaluation.
Start a transaction with BEGIN. COMMIT makes its changes permanent.
Use ROLLBACK to discard uncommitted changes in the current transaction after an error.
ROLLBACK cannot undo changes after COMMIT. Recovery after a commit requires restoring a backup.
This guide does not specify automatic database transaction retries.
