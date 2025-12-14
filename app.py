from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_socketio import SocketIO, emit, join_room
from sqlalchemy.sql import text
from datetime import timedelta

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(days=7)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['JWT_SECRET_KEY'] = 'dot.dot.'
app.config['SECRET_KEY']= '.dot.dot'

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

socketio = SocketIO(app, cors_allowed_origins="*")


################. DATABASE MODELS #####################

class Users(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    
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
    user_colour = db.Column(db.String(7), server_default ='#FFFFFF', nullable=False)  # Hex color number
    user_score = db.Column(db.Integer, server_default='0', nullable=False)

# territories claimed by users on maps
class Territory(db.Model):
    __tablename__ = 'territory'
    id = db.Column(db.Integer, primary_key=True)
    map_id = db.Column(db.Integer, db.ForeignKey('maps_data.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    coordinates = db.Column(db.Text, nullable=False)  # JSON string of coordinates
    color = db.Column(db.String(7), nullable=False)


with app.app_context():
    db.create_all()

################. ROUTES #####################
@app.route('/')
def home():

    return render_template('home.html')

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
        text("SELECT username, latitude, longitude FROM users WHERE id = :id"),
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
                text(" INSERT INTO maps_data (map_name, desc, map_center_lat, map_center_lon, owner_id, num_users) VALUES (:map_name, :desc, :map_center_lat, :map_center_lon, :owner_id, :num_users) "),
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
                text(" INSERT INTO user_map (user_id, map_id) VALUES (:user_id, (SELECT id FROM maps_data WHERE map_name = :map_name AND owner_id = :user_id)) "),
                {'user_id': session['user_id'],'map_name': map_name}
            )
            db.session.commit()
            flash(f'Map "{map_name}" created and joined!')
            return redirect(url_for('dashboard'))

        # Joining an existing map
    if 'join_map_id' in request.form:
        map_to_join = Maps_Data.query.get(int(request.form['join_map_id']))

        # check if already in map
        userin = db.session.execute(
            text("SELECT * FROM user_map WHERE user_id = :user_id AND map_id = :map_id"),
            {'user_id': session['user_id'], 'map_id': map_to_join.id}
        ).fetchone()

        if map_to_join and not userin:

            # add user to map

            colour = "#%06x" % (int(map_to_join.num_users * 1234567) % 0xFFFFFF)  # Generate a pseudo-random color based on num_users
            db.session.execute(
                text("INSERT INTO user_map (user_id, map_id, user_colour) VALUES (:user_id, :map_id, :user_colour) "),
                {'user_id': session['user_id'], 'map_id': map_to_join.id, 'user_colour': colour}
            )
            

            
            db.session.execute(
                text("UPDATE maps_data SET num_users = num_users + 1 WHERE id = :map_id"),
                {'map_id': map_to_join.id}
            )

            db.session.commit()
            flash(f'Joined map \"{map_to_join.map_name}\"!')
        
        return redirect(url_for('dashboard'))


    # Show maps user is currently in
    current_maps = db.session.execute(
        text(" SELECT maps_data.* FROM maps_data JOIN user_map ON maps_data.id = user_map.map_id WHERE user_map.user_id = :user_id "),
        {'user_id': session['user_id']}
    ).fetchall()

    # Show all maps they are NOT in (to join)
    available_maps = db.session.execute(
        text(" SELECT * FROM maps_data WHERE id NOT IN (SELECT map_id FROM user_map WHERE user_id = :user_id) "),
        {'user_id': session['user_id']}
    ).fetchall()

    return render_template('dashboard.html', user=user, current_maps=current_maps, available_maps=available_maps)

@app.route('/map_view')
def map_view():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    map_id = request.args.get('map_id')
    map_data = db.session.execute(
        text(" SELECT * FROM maps_data WHERE id = :map_id "),
        {'map_id': map_id}
    ).fetchone()

    user = db.session.execute(
        text("""
            SELECT users.username, users.latitude, users.longitude , user_map.user_colour
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
        SELECT users.username, users.latitude, users.longitude, user_map.user_colour
        FROM users
        JOIN user_map ON users.id = user_map.user_id
        WHERE user_map.map_id = :map_id
          AND users.id != :user_id
    """),
    {'map_id': map_id, 'user_id': session['user_id']}
).mappings().all()

    friends_list = [dict(friend) for friend in friends]
    #print(friends_list)
    territories = db.session.execute(
        text(" SELECT * FROM territory WHERE map_id = :map_id "),
        {'map_id': map_id}
    ).fetchall()

    territories_list=[{
            'coords': json.loads(t.coordinates),
            'color': t.color
        } for t in territories]
    

    return render_template('map_view.html', map_data=map_data, user=user, friends=friends_list, territories=territories_list)



##############. SOCKET.IO EVENTS #####################
@socketio.on("join_map")
def join_map_room(data):
    join_room(f"map_{data['map_id']}")

@socketio.on("update_location")
def update_location_socket(data):
    user_id = session.get("user_id")
    lat = data["latitude"]
    lon = data["longitude"]
    map_id = data["map_id"]

    db.session.execute(
        text("UPDATE users SET latitude=:lat, longitude=:lon WHERE id=:u"),
        {'lat': lat, 'lon': lon, 'u': user_id}
    )
    db.session.commit()

    emit(
        "player_moved",
        {"user_id": user_id, "lat": lat, "lon": lon},
        room=f"map_{map_id}",
        include_self=False
    )

@socketio.on("territory_created")
def territory_created(data):
    map_id = data["map_id"]
    coords = data["coords"]
    color = data["color"]
    user_id = session.get("user_id")

    db.session.add(Territory(
        map_id=map_id,
        user_id=user_id,
        coordinates=json.dumps(coords),
        color=color
    ))
    db.session.commit()

    emit(
        "new_territory",
        {"coords": coords, "color": color},
        room=f"map_{map_id}",
        include_self=False
    )
if __name__ == '__main__':
    socketio.run(app, debug=True)