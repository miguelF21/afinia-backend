import uuid
from datetime import datetime
from app import db

class LegalConsent(db.Model):
    __tablename__ = 'legal_consents'

    ALLOWED_DOCUMENT_TYPES = ('terms_of_service', 'privacy_policy')

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False, index=True)
    document_type = db.Column(db.String(50), nullable=False, index=True)
    document_version = db.Column(db.String(50), nullable=False)
    accepted_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, server_default=db.text('CURRENT_TIMESTAMP'), nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=True)

    # Relación
    user = db.relationship('User', back_populates='legal_consents')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'document_type', 'document_version', name='uq_legal_consents_user_doc_version'),
        db.CheckConstraint("document_type IN ('terms_of_service', 'privacy_policy')", name='ck_legal_consents_doc_type'),
    )

    def __repr__(self):
        return f'<LegalConsent {self.user_id} {self.document_type}={self.document_version}>'
