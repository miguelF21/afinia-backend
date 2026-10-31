"""expand_user_email_to_254

Revision ID: c0329b1d7d29
Revises: e3e45a9bd485
Create Date: 2026-10-28 13:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c0329b1d7d29'
down_revision = 'e3e45a9bd485'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column(
            'email',
            existing_type=sa.String(length=120),
            type_=sa.String(length=254),
            existing_nullable=False
        )


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column(
            'email',
            existing_type=sa.String(length=254),
            type_=sa.String(length=120),
            existing_nullable=False
        )
