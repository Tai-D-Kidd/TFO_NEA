from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity

app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['JWT_SECRET_KEY'] = 'dot.dot.'
app.config['SECRET_KEY']= '.dot.dot'

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# database 
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

db.create_all()

# routes

#-- 'late registration' - Ye
@app.route('/register', methods=['POST'])
def register():
    data = request.get.json()
    username = data.get('username')
    password = data.get('password')
    
    result = db.session.execute(
        text(" SELECT * FROM users WHERE username = :username "), {'username': username}
    ).fetchone()

    if result:
        # conflict as user alr in databasr
        return jsonify({'message': 'Username already exists'}), 409

    hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')

    db.session.execute(
        text(" INSERT INTO users (username, password) VALUES (:username, :password) "),
        {'username': username, 'password': hashed_pw}
    )
    db.session.commit()
    return jsonify({'message': 'User registered successfully'}), 201 

#-- login --
@app.route('/login', methods=['POST'])
def login():
    data = request.get.json()
    username = data.get('username')
    password = data.get('password')

    result = db.session.execute(
        text(" SELECT * FROM users WHERE username = :username "), {'username': username}
    ).fetchone()

    if not result or not bcrypt.check_password_hash(result.password, password):
        return jsonify({'message': 'Invalid credentials'}), 401

    access_token = create_access_token(identity={'id': result.id, 'username': result.username})
    return jsonify({'access_token': access_token}), 200

    #location update
@app.route('/update_location', methods=['POST'])
@jwt_required()
def update_location():
    current_user = get_jwt_identity()
    data = request.get.json()
    latitude = data.get('latitude')
    longitude = data.get('longitude')

    db.session.execute(
        text(" UPDATE users SET latitude = :latitude, longitude = :longitude WHERE id = :user_id "),
        {'latitude': latitude, 'longitude': longitude, 'user_id': current_user['id']}
    )
    db.session.commit()
    return jsonify({'message': 'Location updated successfully'}), 200

# friends (bassically everyone else)
@app.route('/friends', methods=['GET'])
@jwt_required()
def friends_location():
    current_user = get_jwt_identity()

    results = db.session.execute(
        text(" SELECT username, latitude, longitude FROM users WHERE id != :user_id "),
        {'user_id': current_user['id']}
    ).fetchall()

    friends = [
        {'username': row.username, 'latitude': row.latitude, 'longitude': row.longitude}
        for row in results
    ]

    return jsonify({'friends': friends}), 200

#she a runner she a track star
if __name__ == '__main__':
    app.run(debug=True)