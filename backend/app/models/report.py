import uuid
from datetime import datetime
from app import db

class UserReport(db.Model):
    __tablename__ = 'user_reports'

    ALLOWED_REASONS = ('acoso', 'contenido_inapropiado', 'suplantacion', 'spam', 'otro')
    ALLOWED_STATUSES = ('pending', 'resolved', 'dismissed')
    ALLOWED_ACTIONS = ('dismiss', 'warn', 'suspend')

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reporter_user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False, index=True)
    reported_user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False, index=True)
    reason = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending', server_default=db.text("'pending'"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, server_default=db.text('CURRENT_TIMESTAMP'), nullable=False, index=True)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    resolved_by_user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    resolution_action = db.Column(db.String(20), nullable=True)
    resolution_notes = db.Column(db.Text, nullable=True)

    # Relaciones
    reporter = db.relationship('User', foreign_keys=[reporter_user_id], back_populates='reports_filed')
    reported = db.relationship('User', foreign_keys=[reported_user_id], back_populates='reports_received')
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_user_id], back_populates='reports_resolved')

    __table_args__ = (
        db.CheckConstraint('reporter_user_id <> reported_user_id', name='ck_user_reports_no_self'),
        db.CheckConstraint("reason IN ('acoso', 'contenido_inapropiado', 'suplantacion', 'spam', 'otro')", name='ck_user_reports_reason'),
        db.CheckConstraint("status IN ('pending', 'resolved', 'dismissed')", name='ck_user_reports_status'),
        db.CheckConstraint("resolution_action IS NULL OR resolution_action IN ('dismiss', 'warn', 'suspend')", name='ck_user_reports_resolution_action'),
        db.CheckConstraint(
            "(status = 'pending' AND resolution_action IS NULL AND resolved_at IS NULL) OR "
            "(status = 'dismissed' AND resolution_action = 'dismiss' AND resolved_at IS NOT NULL) OR "
            "(status = 'resolved' AND resolution_action IN ('warn', 'suspend') AND resolved_at IS NOT NULL)",
            name='ck_user_reports_resolution_consistency'
        ),
    )

    def resolve(self, moderator_id, action, notes=None):
        """Método de dominio para resolver una denuncia aplicando coherencia de estados."""
        if action not in self.ALLOWED_ACTIONS:
            raise ValueError(f"Acción no permitida: {action}. Permitidas: {self.ALLOWED_ACTIONS}")
        self.status = 'dismissed' if action == 'dismiss' else 'resolved'
        self.resolution_action = action
        self.resolution_notes = notes
        self.resolved_by_user_id = moderator_id
        self.resolved_at = datetime.utcnow()

    def __repr__(self):
        return f'<UserReport {self.id} ({self.reason}) status={self.status}>'
