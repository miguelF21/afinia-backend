from app import db
import uuid
from datetime import datetime
from sqlalchemy.orm import validates
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.mutable import MutableList

class DiscoveryPreference(db.Model):
    __tablename__ = 'discovery_preferences'

    ALLOWED_GENDERS = ('masculino', 'femenino', 'no_binario', 'otro', 'prefiero_no_indicar')

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), unique=True, nullable=False)
    
    # Campo heredado escalar (mantenido temporalmente para compatibilidad hacia atrás, nullable sin default)
    interested_in_gender = db.Column(db.String(20), nullable=True)
    
    # Campo canónico OpenAPI v1 (Preferences.interested_in_genders) con seguimiento de mutaciones in-place
    interested_in_genders = db.Column(
        MutableList.as_mutable(postgresql.JSONB(astext_type=db.Text()).with_variant(db.JSON, 'sqlite')),
        nullable=True
    )
    
    min_age = db.Column(db.Integer, default=18)
    max_age = db.Column(db.Integer, default=99)
    target_relationship_type = db.Column(db.String(50))
    
    user = db.relationship('User', backref=db.backref('discovery_preference', uselist=False, cascade='all, delete-orphan'))

    __table_args__ = (
        db.CheckConstraint('min_age >= 18', name='ck_discovery_min_age_18'),
        db.CheckConstraint('min_age <= max_age', name='ck_discovery_min_le_max_age'),
    )

    def __init__(self, **kwargs):
        genders = kwargs.get('interested_in_genders')
        gender = kwargs.get('interested_in_gender')

        # Detección y rechazo de incompatibilidad semántica explícita
        if genders is not None and gender is not None:
            genders_set = set(genders)
            if gender == 'ambos' and genders_set != {'masculino', 'femenino'}:
                raise ValueError(
                    f"Conflicto semántico: interested_in_gender='ambos' es incompatible con "
                    f"interested_in_genders={genders}. No se permite inventar equivalencias."
                )
            elif gender in ('masculino', 'femenino') and genders != [gender]:
                raise ValueError(
                    f"Conflicto semántico: interested_in_gender='{gender}' es incompatible con "
                    f"interested_in_genders={genders}."
                )
        elif genders is not None and gender is None:
            # Derivar legacy interested_in_gender estrictamente sin inventar equivalencias
            genders_set = set(genders)
            if genders_set == {'masculino', 'femenino'}:
                kwargs['interested_in_gender'] = 'ambos'
            elif len(genders) == 1 and genders[0] in ('masculino', 'femenino'):
                kwargs['interested_in_gender'] = genders[0]
            else:
                # Combinaciones no binarias o múltiples no tienen equivalente escalar legado
                kwargs['interested_in_gender'] = None
        elif gender is not None and genders is None:
            # Derivar genders canónico a partir del escalar legado
            if gender == 'ambos':
                kwargs['interested_in_genders'] = ['masculino', 'femenino']
            elif gender in self.ALLOWED_GENDERS:
                kwargs['interested_in_genders'] = [gender]
            else:
                kwargs['interested_in_genders'] = None

        super().__init__(**kwargs)

    @property
    def canonical_interested_in_genders(self):
        """
        Única fuente canónica de lectura para OpenAPI v1.
        Retorna la lista de géneros. Si es None, representa preferencias no configuradas aún.
        """
        if self.interested_in_genders is not None:
            return list(self.interested_in_genders)
        if self.interested_in_gender:
            if self.interested_in_gender == 'ambos':
                return ['masculino', 'femenino']
            elif self.interested_in_gender in ('masculino', 'femenino'):
                return [self.interested_in_gender]
        return None

    @validates('interested_in_genders')
    def validate_genders(self, key, value):
        if value is not None:
            if not isinstance(value, (list, tuple)):
                raise ValueError("interested_in_genders must be a list")
            if len(value) < 1:
                raise ValueError("interested_in_genders must contain at least 1 item")
            if len(value) != len(set(value)):
                raise ValueError("interested_in_genders must contain unique items (no duplicates)")
            for g in value:
                if g not in self.ALLOWED_GENDERS:
                    raise ValueError(f"Invalid gender value: '{g}'. Allowed: {self.ALLOWED_GENDERS}")
            return list(value)
        return value

