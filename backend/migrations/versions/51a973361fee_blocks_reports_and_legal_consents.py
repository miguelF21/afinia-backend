"""blocks_reports_and_legal_consents

Revision ID: 51a973361fee
Revises: 25d66d72fcf2
Create Date: 2026-10-28 11:34:04.422966

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '51a973361fee'
down_revision = '25d66d72fcf2'
branch_labels = None
depends_on = None


def upgrade():
    # -------------------------------------------------------------------------
    # 1. Tabla user_blocks
    # -------------------------------------------------------------------------
    op.create_table(
        'user_blocks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('blocker_user_id', sa.String(length=36), nullable=False),
        sa.Column('blocked_user_id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['blocker_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['blocked_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('blocker_user_id', 'blocked_user_id', name='uq_user_blocks_pair'),
        sa.CheckConstraint('blocker_user_id <> blocked_user_id', name='ck_user_blocks_no_self')
    )
    op.create_index(op.f('ix_user_blocks_blocker_user_id'), 'user_blocks', ['blocker_user_id'], unique=False)
    op.create_index(op.f('ix_user_blocks_blocked_user_id'), 'user_blocks', ['blocked_user_id'], unique=False)

    # -------------------------------------------------------------------------
    # 2. Tabla user_reports
    # -------------------------------------------------------------------------
    op.create_table(
        'user_reports',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('reporter_user_id', sa.String(length=36), nullable=False),
        sa.Column('reported_user_id', sa.String(length=36), nullable=False),
        sa.Column('reason', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by_user_id', sa.String(length=36), nullable=True),
        sa.Column('resolution_action', sa.String(length=20), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['reporter_user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['reported_user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['resolved_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('reporter_user_id <> reported_user_id', name='ck_user_reports_no_self'),
        sa.CheckConstraint("reason IN ('acoso', 'contenido_inapropiado', 'suplantacion', 'spam', 'otro')", name='ck_user_reports_reason'),
        sa.CheckConstraint("status IN ('pending', 'resolved', 'dismissed')", name='ck_user_reports_status'),
        sa.CheckConstraint("resolution_action IS NULL OR resolution_action IN ('dismiss', 'warn', 'suspend')", name='ck_user_reports_resolution_action'),
        sa.CheckConstraint(
            "(status = 'pending' AND resolution_action IS NULL AND resolved_at IS NULL) OR "
            "(status IN ('resolved', 'dismissed') AND resolution_action IS NOT NULL AND resolved_at IS NOT NULL)",
            name='ck_user_reports_resolution_consistency'
        )
    )
    op.create_index(op.f('ix_user_reports_reporter_user_id'), 'user_reports', ['reporter_user_id'], unique=False)
    op.create_index(op.f('ix_user_reports_reported_user_id'), 'user_reports', ['reported_user_id'], unique=False)
    op.create_index(op.f('ix_user_reports_status'), 'user_reports', ['status'], unique=False)
    op.create_index(op.f('ix_user_reports_created_at'), 'user_reports', ['created_at'], unique=False)
    op.create_index(op.f('ix_user_reports_resolved_by_user_id'), 'user_reports', ['resolved_by_user_id'], unique=False)

    # -------------------------------------------------------------------------
    # 3. Tabla legal_consents
    # -------------------------------------------------------------------------
    op.create_table(
        'legal_consents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('document_type', sa.String(length=50), nullable=False),
        sa.Column('document_version', sa.String(length=50), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'document_type', 'document_version', name='uq_legal_consents_user_doc_version'),
        sa.CheckConstraint("document_type IN ('terms_of_service', 'privacy_policy')", name='ck_legal_consents_doc_type')
    )
    op.create_index(op.f('ix_legal_consents_user_id'), 'legal_consents', ['user_id'], unique=False)
    op.create_index(op.f('ix_legal_consents_document_type'), 'legal_consents', ['document_type'], unique=False)
    op.create_index(op.f('ix_legal_consents_accepted_at'), 'legal_consents', ['accepted_at'], unique=False)


def downgrade():
    # -------------------------------------------------------------------------
    # 1. Eliminar legal_consents
    # -------------------------------------------------------------------------
    op.drop_index(op.f('ix_legal_consents_accepted_at'), table_name='legal_consents')
    op.drop_index(op.f('ix_legal_consents_document_type'), table_name='legal_consents')
    op.drop_index(op.f('ix_legal_consents_user_id'), table_name='legal_consents')
    op.drop_table('legal_consents')

    # -------------------------------------------------------------------------
    # 2. Eliminar user_reports
    # -------------------------------------------------------------------------
    op.drop_index(op.f('ix_user_reports_resolved_by_user_id'), table_name='user_reports')
    op.drop_index(op.f('ix_user_reports_created_at'), table_name='user_reports')
    op.drop_index(op.f('ix_user_reports_status'), table_name='user_reports')
    op.drop_index(op.f('ix_user_reports_reported_user_id'), table_name='user_reports')
    op.drop_index(op.f('ix_user_reports_reporter_user_id'), table_name='user_reports')
    op.drop_table('user_reports')

    # -------------------------------------------------------------------------
    # 3. Eliminar user_blocks
    # -------------------------------------------------------------------------
    op.drop_index(op.f('ix_user_blocks_blocked_user_id'), table_name='user_blocks')
    op.drop_index(op.f('ix_user_blocks_blocker_user_id'), table_name='user_blocks')
    op.drop_table('user_blocks')
