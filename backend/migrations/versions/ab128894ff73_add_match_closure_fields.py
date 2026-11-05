"""add_match_closure_fields

Revision ID: ab128894ff73
Revises: 9f1d4a8e2b6c
Create Date: 2026-11-01 22:55:59.417887

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ab128894ff73'
down_revision = '9f1d4a8e2b6c'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Columnas nullable para ciclo de vida de cierre lógico en matches
    op.add_column('matches', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('matches', sa.Column('closed_by_user_id', sa.String(length=36), nullable=True))

    # 2. Clave foránea con política RESTRICT para integridad y retención legal
    op.create_foreign_key(
        'fk_matches_closed_by_user_id',
        'matches', 'users',
        ['closed_by_user_id'], ['id'],
        ondelete='RESTRICT'
    )

    # 3. Restricción CHECK: consistencia atómica entre fecha y usuario ejecutor del cierre
    op.create_check_constraint(
        'ck_matches_closure_consistency',
        'matches',
        '(closed_at IS NULL AND closed_by_user_id IS NULL) OR (closed_at IS NOT NULL AND closed_by_user_id IS NOT NULL)'
    )

    # 4. Restricción CHECK: el usuario ejecutor debe ser necesariamente uno de los dos participantes
    op.create_check_constraint(
        'ck_matches_closed_by_participant',
        'matches',
        'closed_by_user_id IS NULL OR closed_by_user_id IN (user_a_id, user_b_id)'
    )

    # 5. Índices compuestos para acelerar la consulta de coincidencias activas por participante
    op.create_index('ix_matches_user_a_closed', 'matches', ['user_a_id', 'closed_at'])
    op.create_index('ix_matches_user_b_closed', 'matches', ['user_b_id', 'closed_at'])


def downgrade():
    # Protección de rollback: impedir que una reversión de esquema reactive matches cerrados
    # y destruya evidencia de quién y cuándo solicitó el cierre.
    bind = op.get_bind()
    closed_count = bind.execute(sa.text("SELECT COUNT(*) FROM matches WHERE closed_at IS NOT NULL")).scalar()
    if closed_count and closed_count > 0:
        raise RuntimeError(
            f"Rollback abortado por seguridad e integridad de datos: existen {closed_count} "
            "coincidencia(s) cerrada(s) con closed_at IS NOT NULL. Revertir el esquema reactivaría "
            "estas relaciones y destruiría la trazabilidad legal del unmatch. Se requiere una "
            "estrategia aprobada de migración antes de proceder."
        )

    op.drop_index('ix_matches_user_b_closed', table_name='matches')
    op.drop_index('ix_matches_user_a_closed', table_name='matches')
    op.drop_constraint('ck_matches_closed_by_participant', 'matches', type_='check')
    op.drop_constraint('ck_matches_closure_consistency', 'matches', type_='check')
    op.drop_constraint('fk_matches_closed_by_user_id', 'matches', type_='foreignkey')
    op.drop_column('matches', 'closed_by_user_id')
    op.drop_column('matches', 'closed_at')
