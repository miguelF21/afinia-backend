"""integrity_security_and_contract_fixes

Revision ID: 25d66d72fcf2
Revises: cf7af2f624fe
Create Date: 2026-10-28 10:41:13.718246

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '25d66d72fcf2'
down_revision = 'cf7af2f624fe'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Modificaciones sobre profile_photos:
    #    - Cambiar server_default de status a 'pending' (verificación previa antes de habilitación)
    #    - Garantizar unicidad de storage_key para evitar reutilización indebida de objetos
    with op.batch_alter_table('profile_photos', schema=None) as batch_op:
        batch_op.alter_column('status',
            existing_type=sa.String(length=20),
            server_default=sa.text("'pending'"),
            existing_nullable=False
        )
        batch_op.create_unique_constraint('uq_profile_photos_storage_key', ['storage_key'])

    # 2. Modificaciones sobre discovery_preferences:
    #    - Permitir que el campo legado interested_in_gender sea nullable y sin default 'ambos'
    #      para evitar inserciones inconsistentes por defecto en SQL directo
    with op.batch_alter_table('discovery_preferences', schema=None) as batch_op:
        batch_op.alter_column('interested_in_gender',
            existing_type=sa.String(length=20),
            nullable=True,
            server_default=None,
            existing_nullable=False
        )

    # 3. Restricción física CHECK sobre interested_in_genders:
    #    - Asegura que cuando no sea NULL, sea un arreglo JSON no vacío (longitud >= 1)
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == 'postgresql':
        op.create_check_constraint(
            'ck_discovery_preferences_genders_array',
            'discovery_preferences',
            "interested_in_genders IS NULL OR (jsonb_typeof(interested_in_genders) = 'array' AND jsonb_array_length(interested_in_genders) >= 1)"
        )
    elif dialect == 'sqlite':
        op.create_check_constraint(
            'ck_discovery_preferences_genders_array',
            'discovery_preferences',
            "interested_in_genders IS NULL OR (json_type(interested_in_genders) = 'array' AND json_array_length(interested_in_genders) >= 1)"
        )


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Revertir CHECK constraint en discovery_preferences
    if dialect == 'postgresql':
        op.drop_constraint('ck_discovery_preferences_genders_array', 'discovery_preferences', type_='check')
    elif dialect == 'sqlite':
        # En SQLite las restricciones check se recrean con batch_alter_table si fuera necesario
        pass

    # 2. Revertir interested_in_gender a NOT NULL con default 'ambos'
    #    Backfill de seguridad si existieran filas con NULL
    if dialect == 'postgresql':
        op.execute("UPDATE discovery_preferences SET interested_in_gender = 'ambos' WHERE interested_in_gender IS NULL")
    elif dialect == 'sqlite':
        op.execute("UPDATE discovery_preferences SET interested_in_gender = 'ambos' WHERE interested_in_gender IS NULL")

    with op.batch_alter_table('discovery_preferences', schema=None) as batch_op:
        batch_op.alter_column('interested_in_gender',
            existing_type=sa.String(length=20),
            nullable=False,
            server_default=sa.text("'ambos'"),
            existing_nullable=True
        )

    # 3. Revertir profile_photos
    with op.batch_alter_table('profile_photos', schema=None) as batch_op:
        batch_op.drop_constraint('uq_profile_photos_storage_key', type_='unique')
        batch_op.alter_column('status',
            existing_type=sa.String(length=20),
            server_default=sa.text("'ready'"),
            existing_nullable=False
        )
