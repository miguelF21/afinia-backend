from app import db
import uuid
from datetime import datetime

class Match(db.Model):
    __tablename__ = 'matches'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_a_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    user_b_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relación de mensajes (sin cascada de eliminación para evitar pérdidas de historial de chat)
    messages = db.relationship('Message', back_populates='match', order_by='Message.sent_at', passive_deletes=True)

    # Restricción: Un match único entre A y B (forzando orden canónico user_a_id < user_b_id para garantizar unicidad bidireccional)
    __table_args__ = (
        db.UniqueConstraint('user_a_id', 'user_b_id', name='uq_match_pair'),
        db.CheckConstraint('user_a_id < user_b_id', name='ck_match_ordered_pair'),
        db.CheckConstraint('user_a_id <> user_b_id', name='ck_match_no_self'),
    )
