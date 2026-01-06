from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_socketio import SocketIO, emit, join_room
from sqlalchemy.sql import text
from datetime import timedelta
import math
import json
from game_models import Player, GameMap, GameController, GameTerritory

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(days=7)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///thebase3.db'
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
    
class Maps_Data(db.Model):
    __tablename__ = 'maps_data'
    id = db.Column(db.Integer, primary_key=True)
    map_name = db.Column(db.String(100), nullable=False)
    desc= db.Column(db.String(255), nullable=True)
    map_center_lat = db.Column(db.Float, nullable=False)
    map_center_lon = db.Column(db.Float, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    num_users = db.Column(db.Integer, default=0)
    
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

with app.app_context():
    db.create_all()

################. HELPERS #####################


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
        return redirect(url_for('login'))
    return render_template('register.html')

#-- login --
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    else:
        username = request.form['username']
        password = request.form['password']

        result = db.session.execute(
            text(" SELECT * FROM users WHERE username = :username "), {'username': username}
        ).fetchone()

        if not result or not bcrypt.check_password_hash(result.password, password):
            flash('Invalid username or password. Please try again.')
            return redirect(url_for('login'))

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



@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    user = db.session.execute(
        text("""
            SELECT username, latitude, longitude 
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
            
            # into db
            db.session.execute(
                text("""
                    INSERT INTO maps_data (map_name, desc, map_center_lat, map_center_lon, owner_id, num_users) 
                    VALUES (:map_name, :desc, :map_center_lat, :map_center_lon, :owner_id, :num_users) 
                    """),
                {
                    'map_name': map_name,
                    'desc': request.form.get('desc', ''),
                    'map_center_lat': map_center_lat,
                    'map_center_lon': map_center_lon,
                    'owner_id': session['user_id'],
                    'num_users': 1

                }
            )
            db.session.commit()
            
            # add owner to this map
            db.session.execute(
                text("""
                    INSERT INTO user_map (user_id, map_id, user_color) 
                    VALUES (:user_id, (SELECT id FROM maps_data WHERE map_name = :map_name AND owner_id = :user_id), :user_color) 
                    """),
                {'user_id': session['user_id'],'map_name': map_name, 'user_color': name2color(session['username'])}
            )
            db.session.commit()
            flash(f'Map "{map_name}" created and joined!')
            return redirect(url_for('dashboard'))

        # Joining an existing map
    if 'join_map_id' in request.form:
        map_to_join = Maps_Data.query.get(int(request.form['join_map_id']))

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
            flash(f'Joined map \"{map_to_join.map_name}\"!')
        
        return redirect(url_for('dashboard'))


    # Show maps user is currently in
    current_maps = db.session.execute(
        text("""
            SELECT maps_data.* FROM maps_data 
            JOIN user_map ON maps_data.id = user_map.map_id WHERE user_map.user_id = :user_id 
             """),
        {'user_id': session['user_id']}
    ).fetchall()

    # Show all maps they are NOT in (to join)
    available_maps = db.session.execute(
        text("""
            SELECT * FROM maps_data 
            WHERE id NOT IN (SELECT map_id FROM user_map WHERE user_id = :user_id) 
            """),
        {'user_id': session['user_id']}
    ).fetchall()

    return render_template('dashboard.html', user=user, current_maps=current_maps, available_maps=available_maps)

@app.route('/map_view')
def map_view():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    map_id = int(request.args.get('map_id'))


    game_map = get_or_create_game(map_id)

    # Ensure current user is added to the game
    if session['user_id'] not in game_map.players:
        user_color = name2color(session['username'])
        player = Player(session['user_id'], session['username'], user_color)
        game_map.add_player(player)

    map_data = db.session.execute(
        text(" SELECT * FROM maps_data WHERE id = :map_id "),
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

    return render_template('map_view.html',
                            map_data=map_data, 
                            user=user, 
                            friends=friends_list, 
                            territories=territories_list,
                            trails=trails_list,
                            leaderboard=leaderboard_list)

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        db.session.execute(
            text("UPDATE users SET is_online = 0 WHERE id = :user_id"),
            {'user_id': user_id}
        )
        db.session.commit()
    
    session.clear()
    flash('Logged out successfully.')
    return redirect(url_for('home'))



##############. SOCKET.IO EVENTS #####################


@socketio.on("join_map")
def join_map_room(data):
    map_id = data['map_id']
    join_room(f"map_{map_id}")

    user_id = session.get('user_id')
    
    if user_id:
        # Mark user as online
        db.session.execute(
            text("UPDATE users SET is_online = 1 WHERE id = :user_id"),
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

@socketio.on("update_location")
def update_location_socket(data):
    user_id = data.get("user_id") or session.get("user_id")
    
    
    if not user_id:
        return
    
    lat = data["latitude"]
    lon = data["longitude"]
    map_id = data["map_id"]

    db.session.execute(
        text("UPDATE users SET latitude=:lat, longitude=:lon WHERE id=:u"),
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
            text("DELETE FROM trails WHERE map_id = :map_id AND user_id = :user_id"),
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
            text("DELETE FROM trails WHERE map_id = :map_id AND user_id = :user_id"),
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
        points = int(territory.area * 10015 * (10**5))  # circa 1 pint per 10 sqm
        db.session.execute(
            text("""
                UPDATE user_map
                SET user_score = user_score + :points
                WHERE user_id = :user_id AND map_id = :map_id
            """),
            {"points": points, "user_id": user_id, "map_id": map_id}
        )
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
        
        # Send trail cleared event
        emit("clear_trail", {"user_id": user_id}, room=f"map_{map_id}")
    else:
         # Update/create trail in database
        existing_trail = db.session.execute(
            text("SELECT coordinates FROM trails WHERE map_id = :map_id AND user_id = :user_id"),
            {'map_id': map_id, 'user_id': user_id}
        ).fetchone()
        
        if existing_trail:
            # Update existing trail
            trail_coords = json.loads(existing_trail.coordinates)
            trail_coords.append([lat, lon])
            
            db.session.execute(
                text("UPDATE trails SET coordinates = :coords WHERE map_id = :map_id AND user_id = :user_id"),
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
            text("UPDATE users SET is_online = 0 WHERE id = :user_id"),
            {'user_id': user_id}
        )
        db.session.commit()
        print(f"User {user_id} disconnected and marked offline")
    







if __name__ == '__main__':
    socketio.run(app, debug=True)

