from flask import Flask, redirect, send_file

from .management import Management
from .volunteer import Volunteer
from .thought import Thought
from .about import About
from .admin import Admin
from .user import User
from .misc import db
from . import config

app = Flask(__name__)
app.config.from_object(config)

db.init_app(app)

@app.route('/')
def index():
    return redirect('/user/login')

@app.route('/favicon.ico')
def favicon():
    return send_file('favicon.ico')

app.register_blueprint(User)
app.register_blueprint(About)
app.register_blueprint(Admin)
app.register_blueprint(Thought)
app.register_blueprint(Volunteer)
app.register_blueprint(Management)