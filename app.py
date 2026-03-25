from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session

from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_socketio import SocketIO, emit, join_room
from sqlalchemy.sql import text
from datetime import timedelta, datetime
import math
import json
from game_models import Player, GameMap, GameController, GameTerritory
import re
import random
import string

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(days=7)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///thebase6.db'
app.config['JWT_SECRET_KEY'] = 'dot.dot.'
app.config['SECRET_KEY']= '.dot.dot'
app.config['SESSION_TYPE'] = 'filesystem'

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False)

active_games = {}  # map_id -> GameMap instance

################. DATABASE MODELS #####################

class Users(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    latitude = db.Column(db.Float, server_default='0.0', nullable=False)
    longitude = db.Column(db.Float, server_default='0.0', nullable=False)
    is_online = db.Column(db.Integer, server_default='0', nullable=False)  # 0 = offline, 1 = online
    level = db.Column(db.Integer, server_default='1', nullable=False)  
    xp = db.Column(db.Integer, server_default='0', nullable=False)  
    
class Maps_Data(db.Model):
    __tablename__ = 'maps_data'
    id = db.Column(db.Integer, primary_key=True)
    map_name = db.Column(db.String(100), nullable=False)
    desc= db.Column(db.String(255), nullable=True)
    map_center_lat = db.Column(db.Float, nullable=False)
    map_center_lon = db.Column(db.Float, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    num_users = db.Column(db.Integer, default=0)
    map_type = db.Column(db.String(10), server_default='public', nullable=False)  # 'public' or 'private'
    map_code = db.Column(db.String(6), unique=True, nullable=True)  # 6-character code
    win_condition_type = db.Column(db.String(10), server_default='points', nullable=False)  # 'points' or 'time'
    win_condition_value = db.Column(db.Integer, server_default='1000', nullable=False)  # target points or minutes
    game_status = db.Column(db.String(20), server_default='active', nullable=False)  # 'active', 'completed', 'paused'
    game_start_time = db.Column(db.DateTime, nullable=True)
    winner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    
# link between users and maps
class User_Map(db.Model):
    __tablename__ = 'user_map'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    map_id = db.Column(db.Integer, db.ForeignKey('maps_data.id'), nullable=False)
    user_color = db.Column(db.String(7), server_default ='#FFFFFF', nullable=False)  # Hex color number
    user_score = db.Column(db.Integer, server_default='0', nullable=False)

# territories claimed by users on maps
class Territory(db.Model):
    __tablename__ = 'territories'
    id = db.Column(db.Integer, primary_key=True)
    map_id = db.Column(db.Integer, db.ForeignKey('maps_data.id'), nullable=False)
    color = db.Column(db.String(7), nullable=False)  # Hex color number 
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    coordinates = db.Column(db.Text, nullable=False)  
    area = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

class Trail(db.Model):
    __tablename__ = 'trails'
    id = db.Column(db.Integer, primary_key=True)
    map_id = db.Column(db.Integer, db.ForeignKey('maps_data.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    coordinates = db.Column(db.Text, nullable=False)  
    color = db.Column(db.String(7), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class Friendship(db.Model):
    __tablename__ = 'friendships'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), server_default='pending', nullable=False)  # pending, accepted
    created_at = db.Column(db.DateTime, server_default=db.func.now())

with app.app_context():
    db.create_all()

################. HELPERS #####################


def generate_map_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        # Check if code already exists
        existing = db.session.execute(
            text("SELECT id FROM maps_data WHERE map_code = :code"),
            {'code': code}
        ).fetchone()
        if not existing:
            return code

def check_win_condition(map_id):
    map_data = db.session.execute(
        text("""
            SELECT win_condition_type, win_condition_value, game_status, game_start_time
            FROM maps_data
            WHERE id = :map_id
        """),
        {'map_id': map_id}
    ).fetchone()
    
    if not map_data or map_data.game_status != 'active':
        return None
    
    if map_data.win_condition_type == 'points':
        # Check if anyone reached the point threshold
        winner = db.session.execute(
            text("""
                SELECT user_id, user_score
                FROM user_map
                WHERE map_id = :map_id AND user_score >= :target
                ORDER BY user_score DESC
                LIMIT 1
            """),
            {'map_id': map_id, 'target': map_data.win_condition_value}
        ).fetchone()
        
        if winner:
            return {'user_id': winner.user_id, 'score': winner.user_score, 'type': 'points'}
    
    elif map_data.win_condition_type == 'time':
        # Check if time has elapsed
        if map_data.game_start_time:
            
            print(type(map_data.game_start_time))
            elapsed = datetime.now() - datetime.strptime(
    map_data.game_start_time,
    "%Y-%m-%d %H:%M:%S.%f"
)
            elapsed_minutes = elapsed.total_seconds() / 60
            
            if elapsed_minutes >= map_data.win_condition_value:
                # Find player with highest score
                winner = db.session.execute(
                    text("""
                        SELECT user_id, user_score
                        FROM user_map
                        WHERE map_id = :map_id
                        ORDER BY user_score DESC
                        LIMIT 1
                    """),
                    {'map_id': map_id}
                ).fetchone()
                
                if winner:
                    return {'user_id': winner.user_id, 'score': winner.user_score, 'type': 'time'}
    
    return None

def end_game(map_id, winner_id):
    db.session.execute(
        text("""
            UPDATE maps_data
            SET game_status = 'completed', winner_id = :winner_id
            WHERE id = :map_id
        """),
        {'map_id': map_id, 'winner_id': winner_id}
    )
    db.session.commit()

def get_game_progress(map_id):
    map_data = db.session.execute(
        text("""
            SELECT win_condition_type, win_condition_value, game_start_time
            FROM maps_data
            WHERE id = :map_id
        """),
        {'map_id': map_id}
    ).fetchone()
    
    if not map_data:
        return 0
    
    if map_data.win_condition_type == 'points':
        # Get highest score
        highest = db.session.execute(
            text("""
                SELECT MAX(user_score) as max_score
                FROM user_map
                WHERE map_id = :map_id
            """),
            {'map_id': map_id}
        ).fetchone()
        
        if highest and highest.max_score:
            return min(100, (highest.max_score / map_data.win_condition_value) * 100)
        return 0
    
    elif map_data.win_condition_type == 'time':
        if map_data.game_start_time:
            elapsed = datetime.now() - datetime.strptime(
    map_data.game_start_time,
    "%Y-%m-%d %H:%M:%S.%f"
)
            elapsed_minutes = elapsed.total_seconds() / 60
            return min(100, (elapsed_minutes / map_data.win_condition_value) * 100)
        return 0
    
    return 0

def get_or_create_game(map_id):
    
    if map_id not in active_games:
        active_games[map_id] = GameMap(map_id)
        
        # Load other players from database
        users_in_map = db.session.execute(
            text("""
                SELECT users.id, users.username, user_map.user_color
                FROM users
                JOIN user_map ON users.id = user_map.user_id
                WHERE user_map.map_id = :map_id
            """),
            {'map_id': map_id}
        ).fetchall()
        
        for user in users_in_map:
            player = Player(user.id, user.username, user.user_color)
            active_games[map_id].add_player(player)
        # Load existing trails into player objects
        trails = db.session.execute(
            text("""
                SELECT user_id, coordinates
                FROM trails
                WHERE map_id = :map_id
            """),
            {'map_id': map_id}
        ).fetchall()
        
        for trail in trails:
            player = active_games[map_id].get_player(trail.user_id)
            if player:
                # Load trail coordinates into player's trail
                trail_coords = json.loads(trail.coordinates)
                player.trail = [(lat, lon) for lat, lon in trail_coords]
        
        # Load existing territories
        territories = db.session.execute(
            text("""
                SELECT user_id, coordinates, color
                FROM territories
                WHERE map_id = :map_id
            """),
            {'map_id': map_id}
        ).fetchall()
        
        for terr in territories:
            
            polygon = json.loads(terr.coordinates)
            territory = GameTerritory(terr.user_id, polygon)
            active_games[map_id].add_territory(territory)
    
    return active_games[map_id]

def name2color(name):
    # color made from their name so consistent across maps and unique per user
    hash_code = sum(ord(c) for c in name)
    r = (hash_code * 123) % 256
    g = (hash_code * 456) % 256
    b = (hash_code * 789) % 256
    return f'#{r:02x}{g:02x}{b:02x}'

#level calculation made a function so could change to exponential r curve for levels later so its harder to increase as you get to a higher level
def calculate_level(xp):
    return int(math.sqrt(0.01 * xp)) 

def add_xp(user_id, xp_amount):
   
    result = db.session.execute(
        text("""
             SELECT xp, level 
             FROM users 
             WHERE id = :user_id
             """),
        {'user_id': user_id}
    ).fetchone()
    
    new_xp = result.xp + xp_amount
    new_level = calculate_level(new_xp)
    
    db.session.execute(
        text("""
            UPDATE users SET xp = :xp, level = :level 
            WHERE id = :user_id
             """),
        {'xp': new_xp, 'level': new_level, 'user_id': user_id}
    )
    db.session.commit()
    
    return new_level, new_xp

# raw value of area calc is really small and would wnat different scaling
def area_scale_factor(area, mode):
    if mode == 'points':
        return int(area* 10015 * (10**5)) #from test values this is circa 1 point per 10sqm
    if mode == 'xp':
        return int(area* 10015 *(10**4)) #1xp per 1sqm

################. ROUTES #####################
@app.route('/')
def home():

    return render_template('home.html')

#-- 'late registration' - taiYelolu 
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        

        # pwd reqs check
        if (
            len(password) < 8 or
            not re.search(r'[A-Z]', password) or
            not re.search(r'[a-z]', password) or
            not re.search(r'[0-9]', password) or
            not re.search(r'[!@#$%^&*(),.?":{}|<>]', password)
        ):
            flash('Password does not meet requirements')
            return redirect(url_for('register'))
        
        
        result = db.session.execute(
            text(""" 
                SELECT * 
                FROM users 
                WHERE username = :username 
                """), 
                {'username': username}
        ).fetchone() #returns True if user in db

        if result:
            # conflict as user alr in databasr
            flash('Username already exists. Please choose a different one.')
            return redirect(url_for('register'))

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')

        db.session.execute(
            text("""
                 INSERT INTO users (username, password) 
                 VALUES (:username, :password) 
                 """),
            {'username': username, 'password': hashed_pw}
        )
        db.session.commit()
        flash('Registration successful! Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

#-- low jin --
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    else:
        username = request.form['username']
        password = request.form['password']

        result = db.session.execute(
            text("""
                SELECT * 
                FROM users 
                WHERE username = :username 
                """), {'username': username}
        ).fetchone()

        if not result or not bcrypt.check_password_hash(result.password, password):
            flash('Invalid username or password. Please try again.')
            return redirect(url_for('login'))

        #saving user sessinon
        session['user_id'] = result.id
        session['username'] = result.username
        flash('Login successful!')
        return redirect(url_for('dashboard'))

#-- changing your location  
@app.route('/update_location', methods=['POST'])
def update_location():
    if 'user_id' not in session:
        return jsonify({'error': 'login first'}), 401
    data = request.get_json()
    latitude = data.get('latitude')
    longitude = data.get('longitude')

    db.session.execute(
        text("""
             UPDATE users 
             SET latitude = :latitude, longitude = :longitude 
             WHERE id = :user_id 
             """),
        {'latitude': latitude, 'longitude': longitude, 'user_id': session['user_id']}
    )
    db.session.commit()
    return jsonify({'message': 'Location updated successfully'}), 200


#-- the (-)board 
@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    user = db.session.execute(
        text("""
            SELECT username, latitude, longitude, level, xp 
            FROM users WHERE id = :id
            """),
        {'id': session['user_id']}
    ).fetchone()
    if request.method == 'POST':
        # Creating a new map
        if 'map_name' in request.form:
            map_name = request.form['map_name']
            map_center_lat = float(request.form.get('map_center_lat', 0))
            map_center_lon = float(request.form.get('map_center_lon', 0))
            map_type = request.form.get('map_type', 'public')
            win_condition_type = request.form.get('win_condition_type', 'points')
            if win_condition_type == 'points':
                win_condition_value = int(request.form.get('win_condition_value_points',10000))
            elif win_condition_type == 'time':
                win_condition_value = int(request.form.get('win_condition_value_time',30))
            
            # Generate unique code
            map_code = generate_map_code()
            
            # into db
            db.session.execute(
                text("""
                    INSERT INTO maps_data (map_name, desc, map_center_lat, map_center_lon, owner_id, num_users,
                                          map_type, map_code, win_condition_type, win_condition_value, 
                                          game_status, game_start_time) 
                    VALUES (:map_name, :desc, :map_center_lat, :map_center_lon, :owner_id, :num_users,
                           :map_type, :map_code, :win_condition_type, :win_condition_value,
                           :game_status, :game_start_time) 
                    """),
                {
                    'map_name': map_name,
                    'desc': request.form.get('desc', ''),
                    'map_center_lat': map_center_lat,
                    'map_center_lon': map_center_lon,
                    'owner_id': session['user_id'],
                    'num_users': 1,
                    'map_type': map_type,
                    'map_code': map_code,
                    'win_condition_type': win_condition_type,
                    'win_condition_value': win_condition_value,
                    'game_status': 'active',
                    'game_start_time': datetime.now()
                }
            )
            db.session.commit()
            
            # add owner to this map
            db.session.execute(
                text("""
                    INSERT INTO user_map (user_id, map_id, user_color) 
                    VALUES (:user_id, (SELECT id FROM maps_data WHERE map_code = :map_code), :user_color) 
                    """),
                {'user_id': session['user_id'], 'map_code': map_code, 'user_color': name2color(session['username'])}
            )
            db.session.commit()
            flash(f'Map "{map_name}" created! Code: {map_code}')
            return redirect(url_for('dashboard'))

        # Joining an existing map by ID (public maps)
        if 'join_map_id' in request.form:
            map_to_join = db.session.execute(
                text("""
                    SELECT *
                    FROM maps_data
                    WHERE id = :map_id
                    LIMIT 1
                """),
                {"map_id": int(request.form["join_map_id"])}
            ).fetchone()

            # check if already in map
            userin = db.session.execute(
                text("""
                    SELECT * 
                    FROM user_map 
                    WHERE user_id = :user_id AND map_id = :map_id
                    """),
                {'user_id': session['user_id'], 'map_id': map_to_join.id}
            ).fetchone()

            if map_to_join and not userin:

                # add user to map

                color = name2color(session['username'])
                db.session.execute(
                    text("""
                        INSERT INTO user_map (user_id, map_id, user_color) 
                        VALUES (:user_id, :map_id, :user_color)
                        """),
                    {'user_id': session['user_id'], 'map_id': map_to_join.id, 'user_color': color}
                )
                

                
                db.session.execute(
                    text("""
                        UPDATE maps_data SET num_users = num_users + 1 
                        WHERE id = :map_id
                        """),
                    {'map_id': map_to_join.id}
                )

                db.session.commit()
                flash(f'Joined map "{map_to_join.map_name}"!')
        
            return redirect(url_for('dashboard'))
        
        # Joining via code (for private maps)
        if 'join_code' in request.form:
            code = request.form['join_code'].upper().strip()
            
            map_to_join = db.session.execute(
                text("""
                    SELECT id, map_name, game_status
                    FROM maps_data
                    WHERE map_code = :code
                """),
                {'code': code}
            ).fetchone()
            
            if not map_to_join:
                flash('Invalid map code!')
                return redirect(url_for('dashboard'))
            
            if map_to_join.game_status == 'completed':
                flash('This game has already ended!')
                return redirect(url_for('dashboard'))
            
            # Check if already in map
            userin = db.session.execute(
                text("""
                    SELECT * 
                    FROM user_map 
                    WHERE user_id = :user_id AND map_id = :map_id
                    """),
                {'user_id': session['user_id'], 'map_id': map_to_join.id}
            ).fetchone()
            
            if not userin:
                color = name2color(session['username'])
                db.session.execute(
                    text("""
                        INSERT INTO user_map (user_id, map_id, user_color) 
                        VALUES (:user_id, :map_id, :user_color)
                        """),
                    {'user_id': session['user_id'], 'map_id': map_to_join.id, 'user_color': color}
                )
                
                db.session.execute(
                    text("""
                        UPDATE maps_data SET num_users = num_users + 1 
                        WHERE id = :map_id
                        """),
                    {'map_id': map_to_join.id}
                )
                
                db.session.commit()
                flash(f'Joined map "{map_to_join.map_name}"!')
            else:
                flash('You are already in this map!')
            
            return redirect(url_for('dashboard'))


    # Show maps user is currently in
    current_maps = db.session.execute(
        text("""
            SELECT maps_data.*, 
                   (SELECT username FROM users WHERE id = maps_data.winner_id) as winner_name
            FROM maps_data 
            JOIN user_map ON maps_data.id = user_map.map_id 
            WHERE user_map.user_id = :user_id 
             """),
        {'user_id': session['user_id']}
    ).fetchall()

    # Show only PUBLIC maps they are NOT in (to join)
    available_maps = db.session.execute(
        text("""
            SELECT * FROM maps_data 
            WHERE id NOT IN (SELECT map_id FROM user_map WHERE user_id = :user_id)
            AND map_type = 'public'
            AND game_status = 'active'
            """),
        {'user_id': session['user_id']}
    ).fetchall()

    # Get friends list
    friends = db.session.execute(
        text("""
            SELECT u.id, u.username, u.level, u.is_online
            FROM users u
            JOIN friendships f ON (u.id = f.friend_id OR u.id = f.user_id)
            WHERE (f.user_id = :user_id OR f.friend_id = :user_id)
            AND u.id != :user_id
            AND f.status = 'accepted'
        """),
        {'user_id': session['user_id']}
    ).fetchall()

    # Get pending friend requests
    pending_requests = db.session.execute(
        text("""
            SELECT u.id, u.username, u.level
            FROM users u
            JOIN friendships f ON u.id = f.user_id
            WHERE f.friend_id = :user_id
            AND f.status = 'pending'
        """),
        {'user_id': session['user_id']}
    ).fetchall()

    user_color = name2color(session['username'])

    return render_template('dashboard.html', 
                         user=user,
                         user_color=user_color, 
                         current_maps=current_maps, 
                         available_maps=available_maps,
                         friends=friends,
                         pending_requests=pending_requests)

### FRIENDS
#-- be my friend
@app.route('/send_friend_request', methods=['POST'])
def send_friend_request():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    friend_username = data.get('username')
    
    # Find friend by username
    friend = db.session.execute(
        text("SELECT id FROM users WHERE username = :username"),
        {'username': friend_username}
    ).fetchone()
    
    if not friend:
        return jsonify({'error': 'User not found'}), 404
    
    #edge case of adding yourself which would have been allowed before
    if friend.id == session['user_id']:
        return jsonify({'error': 'Cannot add yourself'}), 400
    
    # Check alr friends
    existing = db.session.execute(
        text("""
            SELECT * FROM friendships 
            WHERE (user_id = :user_id AND friend_id = :friend_id)
            OR (user_id = :friend_id AND friend_id = :user_id)
        """),
        {'user_id': session['user_id'], 'friend_id': friend.id}
    ).fetchone()
    
    if existing:
        return jsonify({'error': 'Friend request already exists'}), 400
    
    # Create friend request
    db.session.execute(
        text("""
            INSERT INTO friendships (user_id, friend_id, status)
            VALUES (:user_id, :friend_id, 'pending')
        """),
        {'user_id': session['user_id'], 'friend_id': friend.id}
    )
    db.session.commit()
    
    return jsonify({'message': 'Friend request sent!'}), 200

#-- I do
@app.route('/accept_friend_request', methods=['POST'])
def accept_friend_request():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    requester_id = data.get('requester_id')
    
    db.session.execute(
        text("""
            UPDATE friendships 
            SET status = 'accepted'
            WHERE user_id = :requester_id AND friend_id = :user_id
        """),
        {'requester_id': requester_id, 'user_id': session['user_id']}
    )
    db.session.commit()
    
    return jsonify({'message': 'Friend request accepted!'}), 200

#-- I don't
@app.route('/reject_friend_request', methods=['POST'])
def reject_friend_request():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    requester_id = data.get('requester_id')
    
    db.session.execute(
        text("""
            DELETE FROM friendships 
            WHERE user_id = :requester_id AND friend_id = :user_id
        """),
        {'requester_id': requester_id, 'user_id': session['user_id']}
    )
    db.session.commit()
    
    return jsonify({'message': 'Friend request rejected'}), 200


#-- Le Plan --
@app.route('/map_view')
def map_view():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    map_id = int(request.args.get('map_id'))


    game_map = get_or_create_game(map_id)

    # Make sure current user is added to the game
    if session['user_id'] not in game_map.players:
        user_color = name2color(session['username'])
        player = Player(session['user_id'], session['username'], user_color)
        game_map.add_player(player)

    map_data = db.session.execute(
        text("""
              SELECT *, 
                     (SELECT username FROM users WHERE id = maps_data.winner_id) as winner_name
             FROM maps_data 
             WHERE id = :map_id 
             """),
        {'map_id': map_id}
    ).fetchone()

    user = db.session.execute(
        text("""
            SELECT users.username, users.latitude, users.longitude , user_map.user_color, users.is_online
            FROM users 
            JOIN user_map ON users.id = user_map.user_id
            WHERE user_map.map_id = :map_id
              AND users.id = :user_id
        """),
        {'map_id': map_id, 'user_id': session['user_id']}
    ).fetchone()
    
    if not map_data:
        flash('Map not found.')
        return redirect(url_for('dashboard'))
    
    friends = db.session.execute(
    text("""
        SELECT users.id, users.username, users.latitude, users.longitude, user_map.user_color, users.is_online
        FROM users
        JOIN user_map ON users.id = user_map.user_id
        WHERE user_map.map_id = :map_id
          AND users.id != :user_id
    """),
    {'map_id': map_id, 'user_id': session['user_id']}
).mappings().all()

    friends_list = [dict(friend) for friend in friends]
    #print(friends_list)
    
    # terries
    
    territories = db.session.execute(
        text("""
            SELECT user_id, area, coordinates, color
            FROM territories
            WHERE map_id = :map_id
        """),
        {"map_id": map_id}
    ).mappings().all()
    territories_list = []
    for t in territories:
        territories_list.append({
            "user_id": t["user_id"],
            "area": t["area"],
            "coordinates": json.loads(t["coordinates"]),
            "color": t["color"] 
        })

    # Load existing trails
    trails = db.session.execute(
        text("""
            SELECT user_id, coordinates, color
            FROM trails
            WHERE map_id = :map_id
        """),
        {"map_id": map_id}
    ).mappings().all()
    
    trails_list = []
    for t in trails:
        trails_list.append({
            "user_id": t["user_id"],
            "coordinates": json.loads(t["coordinates"]),
            "color": t["color"]
        })

    # Leaderboard
    leaderboard = db.session.execute(
        text("""
            SELECT
                users.id AS user_id,
                users.username,
                user_map.user_score,
                user_map.user_color
            FROM user_map
            JOIN users ON users.id = user_map.user_id
            WHERE user_map.map_id = :map_id
            ORDER BY user_map.user_score DESC
        """),
        {"map_id": map_id}
    ).mappings().all()
    leaderboard_list = [dict(entry) for entry in leaderboard]
    
    # Calculate game progress
    game_progress = get_game_progress(map_id)

    return render_template('map_view.html',
                            map_data=map_data, 
                            user=user, 
                            friends=friends_list, 
                            territories=territories_list,
                            trails=trails_list,
                            leaderboard=leaderboard_list,
                            game_progress=game_progress)

#-- leaving
@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        db.session.execute(
            text("""
                 UPDATE users SET is_online = 0 
                 WHERE id = :user_id
                 """),
            {'user_id': user_id}
        )
        db.session.commit()
    
    session.clear()
    flash('Logged out successfully.')
    return redirect(url_for('home'))



##############. SOCKET.IO EVENTS #####################

#entering map you are alr a part of
@socketio.on("join_map")
def join_map_room(data):
    map_id = data['map_id']
    join_room(f"map_{map_id}")

    user_id = session.get('user_id')
    
    if user_id:
        # Mark user as online
        db.session.execute(
            text("""
                 UPDATE users 
                 SET is_online = 1 
                 WHERE id = :user_id
                 """),
            {'user_id': user_id}
        )
        db.session.commit()
        print(f"User {user_id} marked as online")
    
    game_map = get_or_create_game(map_id)
    
    if user_id and user_id not in game_map.players:
        username = session.get('username')
        color = name2color(username)
        player = Player(user_id, username, color)
        game_map.add_player(player)

        trail_data = db.session.execute(
            text("""
                SELECT coordinates
                FROM trails
                WHERE map_id = :map_id AND user_id = :user_id
            """),
            {'map_id': map_id, 'user_id': user_id}
        ).fetchone()
        
        if trail_data:
            trail_coords = json.loads(trail_data.coordinates)
            player.trail = [(lat, lon) for lat, lon in trail_coords]

@socketio.on("update_location")
def update_location_socket(data):
    user_id = data.get("user_id") or session.get("user_id")
    
    
    if not user_id:
        return
    
    lat = data["latitude"]
    lon = data["longitude"]
    map_id = data["map_id"]

    # Check if game is still active
    game_status = db.session.execute(
        text("SELECT game_status FROM maps_data WHERE id = :map_id"),
        {'map_id': map_id}
    ).scalar()
    
    if game_status != 'active':
        emit("game_ended", {"message": "This game has ended"})
        return

    db.session.execute(
        text("""
             UPDATE users 
             SET latitude=:lat, longitude=:lon 
             WHERE id=:u
             """),
        {'lat': lat, 'lon': lon, 'u': user_id}
    )
    db.session.commit()
    # Update game state
    game_map = get_or_create_game(map_id)
    game_controller = GameController(game_map)
    player = game_map.get_player(user_id)

    broken_by = game_controller.check_trail_collision(user_id, lat, lon)
    if broken_by:
        print(f"Player {broken_by} broke Player {user_id}'s trail!")

        # Delete broken trail from database
        db.session.execute(
            text("""
                 DELETE FROM trails 
                 WHERE map_id = :map_id AND user_id = :user_id
                 """),
            {'map_id': map_id, 'user_id': broken_by}
        )
        db.session.commit()

        emit("trail_broken", {
            "broken_user_id": broken_by,
            "breaker_user_id": user_id
        }, room=f"map_{map_id}")
    
    # This will check for loop completion and create territory if needed
    territory = game_controller.update_player_position(user_id, lat, lon)
    
    if territory:
        # A loop was completed > to database

        # Territory created - delete trail from database
        db.session.execute(
            text("""
                 DELETE FROM trails 
                 WHERE map_id = :map_id AND user_id = :user_id
                 """),
            {'map_id': map_id, 'user_id': user_id}
        )

        color = game_map.get_player(user_id).color
        coordinates_json = json.dumps(territory.polygon)
        

        
        db_territory = Territory(
            map_id=map_id,
            user_id=user_id,
            coordinates=coordinates_json,
            area=territory.area,
            color=color
        )
        db.session.add(db_territory)
        # Update score
        points = area_scale_factor(territory.area, 'points')  # circa 1 pint per 10 sqm
        db.session.execute(
            text("""
                UPDATE user_map
                SET user_score = user_score + :points
                WHERE user_id = :user_id AND map_id = :map_id
            """),
            {"points": points, "user_id": user_id, "map_id": map_id}
        )
        
        # Add XP and update level
        xp_gained = max(1, area_scale_factor(territory.area, 'xp'))  # Minimum 1XP, circa 1 xp per sqm
        new_level, new_xp = add_xp(user_id, xp_gained)
        
        db.session.commit()
        
        new_score = db.session.execute(
            text("""
                SELECT user_score FROM user_map
                WHERE user_id = :user_id AND map_id = :map_id
            """),
            {"user_id": user_id, "map_id": map_id}
        ).scalar()
        
        # Broadcast new territory
        emit("new_territory", {
            "coordinates": territory.polygon,
            "user_id": user_id,
            "area": territory.area,
            "color": color
        }, room=f"map_{map_id}")
        
        username = session.get('username')
        emit("score_updated", {
            "username": username,
            "new_score": new_score
        }, room=f"map_{map_id}")
        
        # Broadcast level up if changed
        emit("level_updated", {
            "user_id": user_id,
            "username": username,
            "level": new_level,
            "xp": new_xp,
            "xp_gained": xp_gained
        }, room=f"map_{map_id}")
        
        # Send trail cleared event
        emit("clear_trail", {"user_id": user_id}, room=f"map_{map_id}")
        
        # Check win condition after score update
        winner_info = check_win_condition(map_id)
        if winner_info:
            end_game(map_id, winner_info['user_id'])
            
            winner_username = db.session.execute(
                text("SELECT username FROM users WHERE id = :user_id"),
                {'user_id': winner_info['user_id']}
            ).scalar()
            
            emit("game_won", {
                "winner_id": winner_info['user_id'],
                "winner_username": winner_username,
                "score": winner_info['score'],
                "win_type": winner_info['type']
            }, room=f"map_{map_id}")
    else:
         # Update/create trail in database
        existing_trail = db.session.execute(
            text("""
                 SELECT coordinates 
                 FROM trails WHERE map_id = :map_id AND user_id = :user_id
                 """),
            {'map_id': map_id, 'user_id': user_id}
        ).fetchone()
        
        if existing_trail:
            # Update existing trail
            trail_coords = json.loads(existing_trail.coordinates)
            trail_coords.append([lat, lon])
            
            db.session.execute(
                text("""
                     UPDATE trails 
                     SET coordinates = :coords 
                     WHERE map_id = :map_id AND user_id = :user_id
                     """),
                {'coords': json.dumps(trail_coords), 'map_id': map_id, 'user_id': user_id}
            )
        else:
            # Create new trail
            color = game_map.get_player(user_id).color
            db_trail = Trail(
                map_id=map_id,
                user_id=user_id,
                coordinates=json.dumps([[lat, lon]]),
                color=color
            )
            db.session.add(db_trail)
        
        db.session.commit()
    
    # Update game progress
    progress = get_game_progress(map_id)
    emit("progress_updated", {"progress": progress}, room=f"map_{map_id}")
    
    # Broadcast position update
    emit("player_moved", {
        "user_id": user_id,
        "lat": lat,
        "lon": lon,
        "trail": player.trail
    }, room=f"map_{map_id}", include_self=False)

@socketio.on("disconnect")
def handle_disconnect():
    user_id = session.get("user_id")
    
    if user_id:
        db.session.execute(
            text("""
                 UPDATE users 
                 SET is_online = 0 
                 WHERE id = :user_id
                 """),
            {'user_id': user_id}
        )
        db.session.commit()
        print(f"User {user_id} disconnected and marked offline")
    



 



if __name__ == '__main__':
    socketio.run(app, host="127.0.0.1", port=5001, debug=True)