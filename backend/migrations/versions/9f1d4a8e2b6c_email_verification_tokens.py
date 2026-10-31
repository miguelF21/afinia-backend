"""email_verification_tokens

Revision ID: 9f1d4a8e2b6c
Revises: c0329b1d7d29
Create Date: 2026-10-28 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f1d4a8e2b6c'
down_revision = 'c0329b1d7d29'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'email_verification_tokens',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_email_verification_tokens_user_id', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_email_verification_tokens')
    )
    with op.batch_alter_table('email_verification_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_email_verification_tokens_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_email_verification_tokens_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('email_verification_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_email_verification_tokens_user_id'))
        batch_op.drop_index(batch_op.f('ix_email_verification_tokens_token_hash'))
    op.drop_table('email_verification_tokens')
