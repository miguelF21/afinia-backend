"""user_notifications

Revision ID: a7b3c9d1e5f2
Revises: f4c2d8e1a3b5
Create Date: 2026-11-05 13:15:00.000000

MIGRACIÓN PREPARADA PARA BE-11 (PENDIENTE DE AUTORIZACIÓN):
Crea la tabla 'notifications' para persistir notificaciones del usuario ('new_match', 'new_message')
con aislamiento estricto por user_id, control de duplicados por evento (user_id, type, reference_id)
e índice compuesto para paginación determinista por cursor (user_id, created_at, id).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7b3c9d1e5f2'
down_revision = 'f4c2d8e1a3b5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notifications',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('reference_id', sa.String(length=36), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('CURRENT_TIMESTAMP'),
            nullable=False,
        ),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            name='fk_notifications_user_id',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_notifications'),
        sa.CheckConstraint(
            "type IN ('new_match', 'new_message')",
            name='ck_notifications_type_allowed',
        ),
        sa.CheckConstraint(
            "LENGTH(TRIM(title)) >= 1 AND LENGTH(title) <= 200",
            name='ck_notifications_title_length',
        ),
        sa.UniqueConstraint(
            'user_id',
            'type',
            'reference_id',
            name='uq_notifications_user_type_reference',
        ),
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notifications_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_created_at'), ['created_at'], unique=False)
        batch_op.create_index(
            'ix_notifications_user_created_id',
            ['user_id', 'created_at', 'id'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index('ix_notifications_user_created_id')
        batch_op.drop_index(batch_op.f('ix_notifications_created_at'))
        batch_op.drop_index(batch_op.f('ix_notifications_user_id'))
    op.drop_table('notifications')

