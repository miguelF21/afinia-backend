from app import db
import uuid

class AnalyticQuestionnaireAnswer(db.Model):
    __tablename__ = 'analytic_questionnaire_answers'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    
    variable_name = db.Column(db.String(100), nullable=False, index=True)
    value_numeric = db.Column(db.Integer)
    value_text = db.Column(db.String(255))
    
    user = db.relationship('User', backref=db.backref('questionnaire_answers', lazy='dynamic', cascade='all, delete-orphan'))
