from app import db
import uuid
from datetime import datetime

class DiscoveryPreference(db.Model):
    __tablename__ = 'discovery_preferences'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), unique=True, nullable=False)
    
    interested_in_gender = db.Column(db.String(20), nullable=False, default='ambos')
    min_age = db.Column(db.Integer, default=18)
    max_age = db.Column(db.Integer, default=99)
    target_relationship_type = db.Column(db.String(50))
    
    user = db.relationship('User', backref=db.backref('discovery_preference', uselist=False, cascade='all, delete-orphan'))
