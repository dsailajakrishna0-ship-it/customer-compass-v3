"""Conversation memory: the server keeps a chat's history (E4.1, ADR 0036).

Two tables. `conversations` is one row per conversation (an unguessable id, when it was made and when it
was last used, which is what the time limit counts from). `conversation_messages` holds its messages,
deleted with it. The message ids are a sequence, so the order of a conversation is the order of the ids.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE conversations (
  id UUID PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_used_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX conversations_last_used_idx ON conversations (last_used_at);

CREATE TABLE conversation_messages (
  id BIGSERIAL PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX conversation_messages_conversation_idx ON conversation_messages (conversation_id, id);
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_messages")
    op.execute("DROP TABLE IF EXISTS conversations")
