import uuid
from datetime import datetime
from app import db

from sqlalchemy.orm import validates

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    email_verified = db.Column(db.Boolean, default=False, server_default=db.text('false'), nullable=False)
    lifecycle_status = db.Column(db.String(20), default='pending_profile', server_default=db.text("'pending_profile'"), nullable=False)
    role = db.Column(db.String(12), default='user', server_default=db.text("'user'"), nullable=False)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint(
            "lifecycle_status IN ('pending_profile', 'active', 'suspended', 'deactivated')",
            name='ck_user_lifecycle_status'
        ),
        db.CheckConstraint(
            "role IN ('user', 'moderator', 'admin')",
            name='ck_users_role'
        ),
    )

    # Relaciones
    profile = db.relationship('Profile', back_populates='user', uselist=False, cascade='all, delete-orphan')
    refresh_tokens = db.relationship('RefreshToken', back_populates='user', cascade='all, delete-orphan')
    email_verification_tokens = db.relationship('EmailVerificationToken', back_populates='user', cascade='all, delete-orphan')
    blocks_issued = db.relationship('UserBlock', foreign_keys='UserBlock.blocker_user_id', back_populates='blocker', cascade='all, delete-orphan')
    blocks_received = db.relationship('UserBlock', foreign_keys='UserBlock.blocked_user_id', back_populates='blocked', cascade='all, delete-orphan')
    reports_filed = db.relationship('UserReport', foreign_keys='UserReport.reporter_user_id', back_populates='reporter')
    reports_received = db.relationship('UserReport', foreign_keys='UserReport.reported_user_id', back_populates='reported')
    reports_resolved = db.relationship('UserReport', foreign_keys='UserReport.resolved_by_user_id', back_populates='resolved_by')
    legal_consents = db.relationship('LegalConsent', back_populates='user')
    messages_sent = db.relationship('Message', back_populates='sender', passive_deletes=True)

    @validates('email')
    def validate_and_normalize_email(self, key, value):
        if not value:
            raise ValueError("El correo electrónico es requerido.")
        value = value.strip().lower()
        if len(value) > 254:
            raise ValueError("El correo electrónico no puede superar los 254 caracteres.")
        return value

    def __repr__(self):
        return f'<User {self.email}>'
