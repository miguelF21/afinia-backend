from app import db
import uuid
from datetime import datetime

class ProfileInteraction(db.Model):
    __tablename__ = 'profile_interactions'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    viewer_user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    shown_user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    
    action = db.Column(db.String(10), nullable=False) # 'LIKE' or 'PASS'
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Restricción: Un usuario sólo puede interactuar una vez con el mismo perfil (para no duplicar datos analíticos).
    __table_args__ = (
        db.UniqueConstraint('viewer_user_id', 'shown_user_id', name='uq_viewer_shown'),
        db.CheckConstraint('viewer_user_id <> shown_user_id', name='ck_interaction_no_self'),
        db.CheckConstraint("action IN ('LIKE', 'PASS')", name='ck_interaction_valid_action'),
    )
