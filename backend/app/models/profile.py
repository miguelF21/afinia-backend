import uuid
from datetime import datetime
from app import db

class Profile(db.Model):
    __tablename__ = 'profiles'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), unique=True, nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    birth_date = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(20), nullable=False)
    city = db.Column(db.String(100))
    bio = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    user = db.relationship('User', back_populates='profile')
    photos = db.relationship('ProfilePhoto', back_populates='profile', cascade='all, delete-orphan', order_by='ProfilePhoto.position')

    @property
    def public_photos(self):
        """Retorna únicamente fotografías con status 'ready' para exposición en perfiles públicos."""
        return [p for p in self.photos if p.status == 'ready']

    def __repr__(self):
        return f'<Profile {self.first_name}>'


class ProfilePhoto(db.Model):
    __tablename__ = 'profile_photos'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    profile_id = db.Column(db.String(36), db.ForeignKey('profiles.id', ondelete='CASCADE'), nullable=False, index=True)
    storage_key = db.Column(db.String(255), nullable=False, unique=True)
    position = db.Column(db.SmallInteger, nullable=False)
    is_primary = db.Column(db.Boolean, default=False, server_default=db.text('false'), nullable=False)
    # Estado inicial 'pending': no se muestra públicamente hasta que el servicio de procesamiento/moderación la apruebe a 'ready'
    status = db.Column(db.String(20), default='pending', server_default=db.text("'pending'"), nullable=False)

    # Metadatos del objeto almacenado
    file_name = db.Column(db.String(255), nullable=True)
    content_type = db.Column(db.String(100), nullable=True)
    byte_size = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, server_default=db.text('CURRENT_TIMESTAMP'), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, server_default=db.text('CURRENT_TIMESTAMP'), nullable=False)

    # Relaciones
    profile = db.relationship('Profile', back_populates='photos')

    __table_args__ = (
        db.UniqueConstraint('storage_key', name='uq_profile_photos_storage_key'),
        db.UniqueConstraint('profile_id', 'position', name='uq_profile_photos_profile_position'),
        db.CheckConstraint('position >= 0 AND position <= 5', name='ck_profile_photos_position_range'),
        db.CheckConstraint("status IN ('pending', 'processing', 'ready', 'rejected')", name='ck_profile_photos_status'),
        db.CheckConstraint('byte_size IS NULL OR (byte_size > 0 AND byte_size <= 10485760)', name='ck_profile_photos_byte_size_10mb'),
        db.Index(
            'uq_profile_photos_primary_per_profile',
            'profile_id',
            unique=True,
            postgresql_where=db.text('is_primary IS TRUE'),
            sqlite_where=db.text('is_primary = 1')
        ),
    )

    def __repr__(self):
        return f'<ProfilePhoto {self.id} (profile={self.profile_id}, pos={self.position}, primary={self.is_primary})>'
