"""Add captcha_task table for manual CAPTCHA solving.

Revision ID: 8f3a2b4c5d6e
Revises: 115759dc7142
Create Date: 2025-01-15 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f3a2b4c5d6e"
down_revision: str | None = "115759dc7142"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create CAPTCHA status enum using raw SQL with IF NOT EXISTS
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE captchastatus AS ENUM ('pending', 'solving', 'solved', 'expired', 'failed');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """
    )

    # Create captcha_task table using raw SQL with IF NOT EXISTS
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS captcha_task (
            id SERIAL PRIMARY KEY,
            uuid UUID NOT NULL,
            url VARCHAR(2048) NOT NULL,
            domain VARCHAR(255) NOT NULL,
            status captchastatus NOT NULL DEFAULT 'pending',
            challenge_type VARCHAR(50),
            error_message TEXT,
            cf_clearance VARCHAR(512),
            user_agent VARCHAR(512),
            cookies_json TEXT,
            request_id VARCHAR(100),
            scrape_options_json TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE,
            solved_at TIMESTAMP WITH TIME ZONE,
            expires_at TIMESTAMP WITH TIME ZONE,
            solver_ip VARCHAR(45),
            attempts INTEGER NOT NULL DEFAULT 0
        );
    """
    )

    # Create indexes using raw SQL with IF NOT EXISTS
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_captcha_task_uuid ON captcha_task (uuid);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_captcha_task_url ON captcha_task (url);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_captcha_task_domain ON captcha_task (domain);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_captcha_task_status ON captcha_task (status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_captcha_task_request_id ON captcha_task (request_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_captcha_task_created_at ON captcha_task (created_at);")


def downgrade() -> None:
    # Drop indexes and table using raw SQL
    op.execute("DROP INDEX IF EXISTS ix_captcha_task_created_at;")
    op.execute("DROP INDEX IF EXISTS ix_captcha_task_request_id;")
    op.execute("DROP INDEX IF EXISTS ix_captcha_task_status;")
    op.execute("DROP INDEX IF EXISTS ix_captcha_task_domain;")
    op.execute("DROP INDEX IF EXISTS ix_captcha_task_url;")
    op.execute("DROP INDEX IF EXISTS ix_captcha_task_uuid;")
    op.execute("DROP TABLE IF EXISTS captcha_task;")
    op.execute("DROP TYPE IF EXISTS captchastatus;")
