"""add_unique_constraint_questionnaire_answers

Revision ID: e3a1f8b2c5d4
Revises: ab128894ff73
Create Date: 2026-11-02 20:10:00.000000

MIGRACIÓN AUTORIZADA PARA POSTGRESQL QA:
Garantiza la unicidad física de (user_id, variable_name) en analytic_questionnaire_answers.
Incluye validación previa de datos para evitar bloqueos por duplicados y estrategia
de reversión segura (downgrade).
"""
from alembic import op
import sqlalchemy as sa

# Identificadores de revisión de Alembic
revision = 'e3a1f8b2c5d4'
down_revision = 'ab128894ff73'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Comprobación defensiva previa: verificar si existen duplicados antes de aplicar
    bind = op.get_bind()
    dup_count = bind.execute(sa.text("""
        SELECT COUNT(*) FROM (
            SELECT user_id, variable_name
            FROM analytic_questionnaire_answers
            GROUP BY user_id, variable_name
            HAVING COUNT(*) > 1
        ) sub
    """)).scalar()

    if dup_count and dup_count > 0:
        raise RuntimeError(
            f"Migración abortada: Existen {dup_count} grupos (user_id, variable_name) con duplicados. "
            "Se requiere saneamiento previo de los registros antes de imponer la restricción UNIQUE."
        )

    # 2. Creación de la restricción de unicidad compuesta
    op.create_unique_constraint(
        'uq_analytic_questionnaire_user_variable',
        'analytic_questionnaire_answers',
        ['user_id', 'variable_name']
    )


def downgrade():
    # Estrategia de reversión (rollback): eliminar la restricción sin alterar los datos existentes
    op.drop_constraint(
        'uq_analytic_questionnaire_user_variable',
        'analytic_questionnaire_answers',
        type_='unique'
    )
