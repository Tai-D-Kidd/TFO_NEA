from math import dist



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


class Territory:
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

        if self.check_loop(player):
            territory = self.create_territory(player)
            self.game_map.add_territory(territory)

            player.score += int(territory.area)
            player.clear_trail()

            return territory

        return None

    # vv internal methods (encapsulation) vv

    def check_loop(self, player, threshold=0.0001):
        
        if len(player.trail) < 4:
            return False

        start = player.trail[0]
        end = player.trail[-1]

        return dist(start, end) < threshold

    def create_territory(self, player):
        polygon = player.trail.copy()
        return Territory(player.user_id, polygon)

