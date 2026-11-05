"""password_reset_tokens

Revision ID: f4c2d8e1a3b5
Revises: e3a1f8b2c5d4
Create Date: 2026-11-03 07:15:00.000000

MIGRACIÓN PREPARADA PARA BE-08 (PENDIENTE DE AUTORIZACIÓN):
Crea la tabla 'password_reset_tokens' para persistencia segura de tokens de restablecimiento
de contraseña con representación hash SHA-256, marcas de consumo, revocación y expiración.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f4c2d8e1a3b5'
down_revision = 'e3a1f8b2c5d4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_password_reset_tokens_user_id', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_password_reset_tokens')
    )
    with op.batch_alter_table('password_reset_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_password_reset_tokens_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_password_reset_tokens_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('password_reset_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_password_reset_tokens_user_id'))
        batch_op.drop_index(batch_op.f('ix_password_reset_tokens_token_hash'))
    op.drop_table('password_reset_tokens')
