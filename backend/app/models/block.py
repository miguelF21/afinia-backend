import uuid
from datetime import datetime
from app import db

class UserBlock(db.Model):
    __tablename__ = 'user_blocks'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    blocker_user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    blocked_user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, server_default=db.text('CURRENT_TIMESTAMP'), nullable=False)

    # Relaciones
    blocker = db.relationship('User', foreign_keys=[blocker_user_id], back_populates='blocks_issued')
    blocked = db.relationship('User', foreign_keys=[blocked_user_id], back_populates='blocks_received')

    __table_args__ = (
        db.UniqueConstraint('blocker_user_id', 'blocked_user_id', name='uq_user_blocks_pair'),
        db.CheckConstraint('blocker_user_id <> blocked_user_id', name='ck_user_blocks_no_self'),
    )

    def __repr__(self):
        return f'<UserBlock {self.blocker_user_id} -> {self.blocked_user_id}>'
