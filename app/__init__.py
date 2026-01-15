"""
Steam Market Web Application
Main Flask application package
"""
from flask import Flask
from flask_session import Session
import os

def create_app():
    """Create and configure the Flask application"""
    app = Flask(__name__, 
                template_folder='../templates',
                static_folder='../static')
    app.secret_key = 'your_secret_key'  # Needed for session
    
    # Configure server-side session
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_FILE_DIR'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'flask_session')
    Session(app)
    
    # Register blueprints/routes
    from app import routes
    app.register_blueprint(routes.bp)
    
    return app
