import uuid
from datetime import datetime, timezone
from app import db


class Notification(db.Model):
    __tablename__ = 'notifications'

    ALLOWED_TYPES = ('new_match', 'new_message')

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    type = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    reference_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=db.text('CURRENT_TIMESTAMP'),
        nullable=False,
        index=True,
    )
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship('User', back_populates='notifications')

    __table_args__ = (
        db.CheckConstraint(
            "type IN ('new_match', 'new_message')",
            name='ck_notifications_type_allowed',
        ),
        db.CheckConstraint(
            "LENGTH(TRIM(title)) >= 1 AND LENGTH(title) <= 200",
            name='ck_notifications_title_length',
        ),
        db.UniqueConstraint(
            'user_id',
            'type',
            'reference_id',
            name='uq_notifications_user_type_reference',
        ),
        db.Index('ix_notifications_user_created_id', 'user_id', 'created_at', 'id'),
    )

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def __repr__(self):
        return f'<Notification {self.id} user={self.user_id} type={self.type} read={self.is_read}>'

