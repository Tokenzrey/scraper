"""Update captcha_task for manual resolver system

Revision ID: a1b2c3d4e5f6
Revises: 8f3a2b4c5d6e
Create Date: 2025-12-15 10:00:00.000000

This migration adds new fields to support the full Manual CAPTCHA Resolver:
- priority: Queue ordering (higher = more urgent)
- assigned_to: Operator assignment for task locking
- preview_path: Screenshot thumbnail for grid UI
- solver_result: JSONB for flexible solution storage
- solver_expires_at: When the solution expires
- metadata: JSONB for extensible metadata
- proxy_url: Proxy used for request
- last_error: Most recent error message
- solver_notes: Notes from operator
- Updated enum with new statuses
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "8f3a2b4c5d6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new enum values to captchastatus
    # PostgreSQL requires ALTER TYPE to add new values
    op.execute(
        """
        DO $$ BEGIN
            ALTER TYPE captchastatus ADD VALUE IF NOT EXISTS 'in_progress';
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """
    )

    op.execute(
        """
        DO $$ BEGIN
            ALTER TYPE captchastatus ADD VALUE IF NOT EXISTS 'unsolvable';
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """
    )

    # Add new columns to captcha_task table
    # Using raw SQL with IF NOT EXISTS pattern for idempotency

    # priority column
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE captcha_task ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 5;
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
    """
    )

    # assigned_to column
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE captcha_task ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(100);
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
    """
    )

    # preview_path column
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE captcha_task ADD COLUMN IF NOT EXISTS preview_path VARCHAR(500);
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
    """
    )

    # solver_result JSONB column
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE captcha_task ADD COLUMN IF NOT EXISTS solver_result JSONB;
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
    """
    )

    # solver_expires_at column
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE captcha_task ADD COLUMN IF NOT EXISTS solver_expires_at TIMESTAMP WITH TIME ZONE;
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
    """
    )

    # proxy_url column
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE captcha_task ADD COLUMN IF NOT EXISTS proxy_url VARCHAR(500);
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
    """
    )

    # last_error column
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE captcha_task ADD COLUMN IF NOT EXISTS last_error TEXT;
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
    """
    )

    # solver_notes column
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE captcha_task ADD COLUMN IF NOT EXISTS solver_notes TEXT;
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
    """
    )

    # metadata JSONB column with default empty object
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE captcha_task ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
    """
    )

    # Create indexes for new columns
    op.execute("CREATE INDEX IF NOT EXISTS ix_captcha_task_priority ON captcha_task (priority);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_captcha_task_assigned_to ON captcha_task (assigned_to);")

    # Create composite index for common query pattern (pending tasks by priority)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_captcha_task_status_priority
        ON captcha_task (status, priority DESC, created_at ASC);
    """
    )


def downgrade() -> None:
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS ix_captcha_task_status_priority;")
    op.execute("DROP INDEX IF EXISTS ix_captcha_task_assigned_to;")
    op.execute("DROP INDEX IF EXISTS ix_captcha_task_priority;")

    # Drop columns (order doesn't matter)
    op.execute("ALTER TABLE captcha_task DROP COLUMN IF EXISTS metadata;")
    op.execute("ALTER TABLE captcha_task DROP COLUMN IF EXISTS solver_notes;")
    op.execute("ALTER TABLE captcha_task DROP COLUMN IF EXISTS last_error;")
    op.execute("ALTER TABLE captcha_task DROP COLUMN IF EXISTS proxy_url;")
    op.execute("ALTER TABLE captcha_task DROP COLUMN IF EXISTS solver_expires_at;")
    op.execute("ALTER TABLE captcha_task DROP COLUMN IF EXISTS solver_result;")
    op.execute("ALTER TABLE captcha_task DROP COLUMN IF EXISTS preview_path;")
    op.execute("ALTER TABLE captcha_task DROP COLUMN IF EXISTS assigned_to;")
    op.execute("ALTER TABLE captcha_task DROP COLUMN IF EXISTS priority;")

    # Note: PostgreSQL doesn't support removing enum values
    # The 'in_progress' and 'unsolvable' values will remain in the enum
