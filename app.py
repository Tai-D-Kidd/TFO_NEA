from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt


from sqlalchemy.sql import text


app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['JWT_SECRET_KEY'] = 'dot.dot.'
app.config['SECRET_KEY']= '.dot.dot'

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)


# databases 
class Users(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

class MapsData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    map_name = db.Column(db.String(100), nullable=False)
    desc= db.Column(db.String(255), nullable=True)
    map_center_lat = db.Column(db.Float, nullable=False)
    map_center_lon = db.Column(db.Float, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

with app.app_context():
    db.create_all()

# routes

@app.route('/')
def home():
    return render_template('login.html')

#-- 'late registration' - Ye
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
    
        result = db.session.execute(
            text(" SELECT * FROM users WHERE username = :username "), {'username': username}
        ).fetchone() #returns True if user in db

        if result:
            # conflict as user alr in databasr
            flash('Username already exists. Please choose a different one.')
            return redirect(url_for('register'))

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')

        db.session.execute(
            text(" INSERT INTO users (username, password) VALUES (:username, :password) "),
            {'username': username, 'password': hashed_pw}
        )
        db.session.commit()
        flash('Registration successful! Please log in.')
        return redirect(url_for('home'))
    return render_template('register.html')

#-- login --
@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']

    result = db.session.execute(
        text(" SELECT * FROM users WHERE username = :username "), {'username': username}
    ).fetchone()

    if not result or not bcrypt.check_password_hash(result.password, password):
        flash('Invalid username or password. Please try again.')
        return redirect(url_for('home'))

    #saving user sessinon
    session['user_id'] = result.id
    session['username'] = result.username
    flash('Login successful!')
    return redirect(url_for('dashboard'))

    


@app.route('/update_location', methods=['POST'])
def update_location():
    if 'user_id' not in session:
        return jsonify({'error': 'login first'}), 401
    data = request.get_json()
    latitude = data.get('latitude')
    longitude = data.get('longitude')

    db.session.execute(
        text(" UPDATE users SET latitude = :latitude, longitude = :longitude WHERE id = :user_id "),
        {'latitude': latitude, 'longitude': longitude, 'user_id': session['user_id']}
    )
    db.session.commit()
    return jsonify({'message': 'Location updated successfully'}), 200


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    user = db.session.execute(
        text("SELECT username, latitude, longitude FROM users WHERE id = :id"),
        {'id': session['user_id']}
    ).fetchone()

    friends = db.session.execute(
        text("SELECT username, latitude, longitude FROM users WHERE id != :id"),
        {'id': session['user_id']}
    ).mappings().all()

    return render_template('dashboard.html', user=user, friends=friends)


#she a runner she a track star
if __name__ == '__main__':
    app.run(debug=True)