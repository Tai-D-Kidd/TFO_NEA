from math import dist, radians, cos, sin, sqrt, atan2



# Player Class


class Player:
    def __init__(self, user_id, username, color):
        self.user_id = user_id
        self.username = username
        self.color = color

        self.lat = None
        self.lon = None

        self.trail = []
        self.score = 0

    def update_position(self, lat, lon):
        self.lat = lat
        self.lon = lon
        self.trail.append((lat, lon))

    def clear_trail(self):
        self.trail = []


# Territory Class


class GameTerritory:
    def __init__(self, owner_id, polygon):
        
        self.owner_id = owner_id
        self.polygon = polygon
        self.area = self.calculate_area()

    def calculate_area(self):
        
        #Shoelace formula (simplified for small geographic areas)
        
        area = 0
        n = len(self.polygon)

        for i in range(n):
            x1, y1 = self.polygon[i]
            x2, y2 = self.polygon[(i + 1) % n]
            area += (x1 * y2) - (x2 * y1)

        return abs(area) / 2

    def contains_point(self, lat, lon):
        # checks if a point is inside the territory polygon using ray-casting algorithm
        inside = False
        x, y = lat, lon
        n = len(self.polygon)

        for i in range(n):
            x1, y1 = self.polygon[i]
            x2, y2 = self.polygon[(i + 1) % n]

            if ((y1 > y) != (y2 > y)) and \
               (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
                inside = not inside

        return inside


# GameMap Class


class GameMap:
    def __init__(self, map_id):
        self.map_id = map_id
        self.players = {}        # user_id -> Player
        self.territories = []    

    def add_player(self, player):
        self.players[player.user_id] = player

    def get_player(self, user_id):
        return self.players.get(user_id)

    def add_territory(self, territory):
        self.territories.append(territory)



# GameController Class


class GameController:

    #Hgame rules and logic
   

    def __init__(self, game_map):
        self.game_map = game_map

    def update_player_position(self, user_id, lat, lon):
        player = self.game_map.get_player(user_id)
        if not player:
            return None

        player.update_position(lat, lon)

        intersection_index = self.check_self_intersection(player)
        
        if intersection_index is not None:
            # Close territory from intersection point
            territory = self.create_territory_from_intersection(player, intersection_index)
            
            if territory:
                self.game_map.add_territory(territory)
                player.score += int(territory.area)
                player.clear_trail()
                return territory

        return None

    def check_self_intersection(self, player, threshold_meters=10):
        
        if len(player.trail) < 4:
            return None

        current_pos = player.trail[-1]
        
        # Check against all previous points (except recent ones)
        for i in range(len(player.trail) - 3):
            prev_pos = player.trail[i]
            distance = self.haversine_distance(
                current_pos[0], current_pos[1],
                prev_pos[0], prev_pos[1]
            )
            
            if distance < threshold_meters:
                print(f"Self-intersection detected at index {i}")
                return i
        
        return None

    def check_trail_collision(self, current_user_id, lat, lon):
        
        threshold_meters = 5  # Distance to "break" a trail
        
        for user_id, player in self.game_map.players.items():
            if user_id == current_user_id:
                continue  # Don't check own trail
            
            if len(player.trail) < 2:
                continue
            
            # Check if current position crosses any segment of other player's trail
            for i in range(len(player.trail) - 1):
                point = player.trail[i]
                distance = self.haversine_distance(lat, lon, point[0], point[1])
                
                if distance < threshold_meters:
                    print(f"Player {current_user_id} broke {user_id}'s trail!")
                    player.clear_trail()
                    return user_id
        
        return None

    def create_territory_from_intersection(self, player, intersection_index):
       
        # Get the loop portion of the trail
        loop = player.trail[intersection_index:]
        
        if len(loop) < 3:
            return None
        
        territory = GameTerritory(player.user_id, loop)
        
        if territory.area < 1/(10015 * (10**5)):
            
            return None
        
        
        return territory

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        # PSA: the earth is not flat
        R = 6371000  # Earth's radius in meters

        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))

        return R * c

    # vv internal methods (encapsulation) vv

    def check_loop(self, player, threshold=0.0001):
        
        if len(player.trail) < 4:
            return False

        start = player.trail[0]
        end = player.trail[-1]

        return dist(start, end) < threshold

    def create_territory(self, player):
        polygon = player.trail.copy()
        return GameTerritory(player.user_id, polygon)

