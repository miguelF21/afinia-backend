import uuid
from datetime import datetime
from app import db

class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id = db.Column(db.String(36), db.ForeignKey('matches.id', ondelete='RESTRICT'), nullable=False)
    sender_user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    sent_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, server_default=db.text('CURRENT_TIMESTAMP'), nullable=False)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relaciones de dominio (sin borrado en cascada para preservar evidencia de conversación)
    match = db.relationship('Match', back_populates='messages')
    sender = db.relationship('User', back_populates='messages_sent')

    __table_args__ = (
        db.CheckConstraint(
            "LENGTH(TRIM(text)) >= 1 AND LENGTH(text) <= 2000",
            name='ck_messages_text_length'
        ),
        db.Index('ix_messages_match_id_sent_at_id', 'match_id', 'sent_at', 'id'),
        db.Index('ix_messages_sender_user_id', 'sender_user_id'),
        db.Index('ix_messages_match_id_read_at', 'match_id', 'read_at'),
    )

    @property
    def is_read(self):
        """Propiedad computada de aplicación; derivada exclusivamente de read_at."""
        return self.read_at is not None

    def __repr__(self):
        return f'<Message {self.id} match={self.match_id} sender={self.sender_user_id}>'
