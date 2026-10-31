"""messages_and_roles

Revision ID: e3e45a9bd485
Revises: 51a973361fee
Create Date: 2026-10-28 11:53:12.863961

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3e45a9bd485'
down_revision = '51a973361fee'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Crear tabla messages
    op.create_table(
        'messages',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('match_id', sa.String(length=36), nullable=False),
        sa.Column('sender_user_id', sa.String(length=36), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('LENGTH(TRIM(text)) >= 1 AND LENGTH(text) <= 2000', name='ck_messages_text_length'),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['sender_user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.create_index('ix_messages_match_id_sent_at_id', ['match_id', 'sent_at', 'id'], unique=False)
        batch_op.create_index('ix_messages_sender_user_id', ['sender_user_id'], unique=False)
        batch_op.create_index('ix_messages_match_id_read_at', ['match_id', 'read_at'], unique=False)

    # 2. Agregar columna role y CHECK a users
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(length=12), server_default=sa.text("'user'"), nullable=False))
        batch_op.create_check_constraint(
            'ck_users_role',
            "role IN ('user', 'moderator', 'admin')"
        )

    # 3. Ajustar restricción de consistencia en user_reports para hacer cumplir dismiss->dismissed y warn/suspend->resolved
    with op.batch_alter_table('user_reports', schema=None) as batch_op:
        batch_op.drop_constraint('ck_user_reports_resolution_consistency', type_='check')
        batch_op.create_check_constraint(
            'ck_user_reports_resolution_consistency',
            "(status = 'pending' AND resolution_action IS NULL AND resolved_at IS NULL) OR "
            "(status = 'dismissed' AND resolution_action = 'dismiss' AND resolved_at IS NOT NULL) OR "
            "(status = 'resolved' AND resolution_action IN ('warn', 'suspend') AND resolved_at IS NOT NULL)"
        )


def downgrade():
    # 3 (reverso). Restaurar restricción previa en user_reports
    with op.batch_alter_table('user_reports', schema=None) as batch_op:
        batch_op.drop_constraint('ck_user_reports_resolution_consistency', type_='check')
        batch_op.create_check_constraint(
            'ck_user_reports_resolution_consistency',
            "(status = 'pending' AND resolution_action IS NULL AND resolved_at IS NULL) OR "
            "(status IN ('resolved', 'dismissed') AND resolution_action IS NOT NULL AND resolved_at IS NOT NULL)"
        )

    # 2 (reverso). Eliminar CHECK y columna role en users
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('ck_users_role', type_='check')
        batch_op.drop_column('role')

    # 1 (reverso). Eliminar índices y tabla messages
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_index('ix_messages_match_id_read_at')
        batch_op.drop_index('ix_messages_sender_user_id')
        batch_op.drop_index('ix_messages_match_id_sent_at_id')

    op.drop_table('messages')
