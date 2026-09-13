from app import db
import uuid
from datetime import datetime

class Match(db.Model):
    __tablename__ = 'matches'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_a_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    user_b_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Restricción: Un match único entre A y B (asumiendo que al insertar siempre ordenamos lexicográficamente user_a_id < user_b_id)
    __table_args__ = (
        db.UniqueConstraint('user_a_id', 'user_b_id', name='uq_match_pair'),
    )
