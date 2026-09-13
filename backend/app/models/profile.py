import uuid
from datetime import datetime
from app import db

class Profile(db.Model):
    __tablename__ = 'profiles'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), unique=True, nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    birth_date = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(20), nullable=False)
    city = db.Column(db.String(100))
    bio = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    user = db.relationship('User', back_populates='profile')

    def __repr__(self):
        return f'<Profile {self.first_name}>'
