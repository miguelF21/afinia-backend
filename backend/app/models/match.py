from app import db
import uuid
from datetime import datetime

class Match(db.Model):
    __tablename__ = 'matches'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_a_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    user_b_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Columnas de ciclo de vida para cierre lógico (soft-close)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    closed_by_user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)

    # Relación de mensajes (sin cascada de eliminación para preservar evidencia de chat)
    messages = db.relationship('Message', back_populates='match', order_by='Message.sent_at', passive_deletes=True)
    closed_by = db.relationship('User', foreign_keys=[closed_by_user_id])

    # Restricciones
    __table_args__ = (
        db.UniqueConstraint('user_a_id', 'user_b_id', name='uq_match_pair'),
        db.CheckConstraint('user_a_id < user_b_id', name='ck_match_ordered_pair'),
        db.CheckConstraint('user_a_id <> user_b_id', name='ck_match_no_self'),
        db.CheckConstraint(
            '((closed_at IS NULL AND closed_by_user_id IS NULL) OR (closed_at IS NOT NULL AND closed_by_user_id IS NOT NULL))',
            name='ck_matches_closure_consistency'
        ),
        db.CheckConstraint(
            '(closed_by_user_id IS NULL OR closed_by_user_id IN (user_a_id, user_b_id))',
            name='ck_matches_closed_by_participant'
        ),
        db.Index('ix_matches_user_a_closed', 'user_a_id', 'closed_at'),
        db.Index('ix_matches_user_b_closed', 'user_b_id', 'closed_at'),
    )

    @property
    def is_active(self) -> bool:
        """Propiedad auxiliar en Python. Para consultas SQLAlchemy utilizar Match.closed_at.is_(None)."""
        return self.closed_at is None

    def __repr__(self):
        status = "closed" if self.closed_at else "active"
        return f'<Match {self.id} ({self.user_a_id} <-> {self.user_b_id}) [{status}]>'
