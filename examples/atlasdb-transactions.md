# AtlasDB transaction guide

AtlasDB is a fictional database used to demonstrate DevDocs AI. These rules are
synthetic documentation, not advice about a real database product.

## Undoing uncommitted changes

Use ROLLBACK to discard all changes in the current, uncommitted transaction.
After an error, roll back the transaction before starting a new one.

## Committing changes

COMMIT makes the transaction's changes permanent. ROLLBACK cannot undo changes
after COMMIT. Restore from an appropriate backup if committed data must be recovered.

## Evidence boundaries

This guide does not specify the default transaction isolation level, retry
settings, backup retention period or support for distributed transactions.
