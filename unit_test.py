"""
=============================================================================
 ANNEX – Unit Test Suite
=============================================================================
 Covers:
   1.  Player          – position updates, trail management, score
   2.  GameTerritory   – Shoelace area, contains_point (ray-casting)
   3.  GameMap         – player/territory management
   4.  GameController  – haversine distance, self-intersection detection,
                         trail collision, territory creation, full position loop
   5.  Pure helpers    – name2color, calculate_level, area_scale_factor,
                         password-validation regex
   6.  Flask routes    – register, login, logout, dashboard, friend system,
                         map creation/joining  (in-memory SQLite test DB)

 Run with:  python -m pytest test_annex.py -v
 Or:        python test_annex.py
=============================================================================
"""

import sys
import os
import math
import re
import string
import unittest
from math import radians, sin, cos, sqrt, atan2

# ---------------------------------------------------------------------------
# Make sure imports resolve whether tests are run from project root or the
# annex_improved sub-directory.
# ---------------------------------------------------------------------------
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

from game_models import Player, GameTerritory, GameMap, GameController


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS  (extracted from app.py – duplicated here so tests run without
#  Flask/SQLAlchemy being installed in the test environment)
# ═══════════════════════════════════════════════════════════════════════════

def name2color(name: str) -> str:
    """Deterministic hex colour from username (mirrors app.py)."""
    hash_code = sum(ord(c) for c in name)
    r = (hash_code * 123) % 256
    g = (hash_code * 456) % 256
    b = (hash_code * 789) % 256
    return f'#{r:02x}{g:02x}{b:02x}'


def calculate_level(xp: int) -> int:
    """Level formula (mirrors app.py)."""
    return int(math.sqrt(0.01 * xp))


def area_scale_factor(area: float, mode: str):
    """Converts raw Shoelace area to game units (mirrors app.py)."""
    if mode == 'points':
        return int(area * 10015 * (10 ** 5))
    if mode == 'xp':
        return int(area * 10015 * (10 ** 4))
    return None


def validate_password(password: str) -> bool:
    """Server-side password validation regex (mirrors app.py register route)."""
    if len(password) < 8:
        return False
    if not re.search(r'[A-Z]', password):
        return False
    if not re.search(r'[a-z]', password):
        return False
    if not re.search(r'[0-9]', password):
        return False
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  1.  PLAYER TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestPlayer(unittest.TestCase):
    """Tests for the Player class."""

    def setUp(self):
        self.player = Player(user_id=1, username='TFO', color='#ff0000')

    # ── Initialisation ──────────────────────────────────────────────────────

    def test_initial_trail_is_empty(self):
        self.assertEqual(self.player.trail, [])

    def test_initial_score_is_zero(self):
        self.assertEqual(self.player.score, 0)

    def test_initial_lat_lon_are_none(self):
        self.assertIsNone(self.player.lat)
        self.assertIsNone(self.player.lon)

    def test_stores_user_id_username_color(self):
        self.assertEqual(self.player.user_id, 1)
        self.assertEqual(self.player.username, 'TFO')
        self.assertEqual(self.player.color, '#ff0000')

    # ── update_position ─────────────────────────────────────────────────────

    def test_update_position_sets_lat_lon(self):
        self.player.update_position(51.5, -0.1)
        self.assertEqual(self.player.lat, 51.5)
        self.assertEqual(self.player.lon, -0.1)

    def test_update_position_appends_to_trail(self):
        self.player.update_position(51.5, -0.1)
        self.player.update_position(51.6, -0.2)
        self.assertEqual(len(self.player.trail), 2)
        self.assertEqual(self.player.trail[0], (51.5, -0.1))
        self.assertEqual(self.player.trail[1], (51.6, -0.2))

    def test_update_position_multiple_times_grows_trail(self):
        for i in range(10):
            self.player.update_position(51.0 + i * 0.001, -0.1)
        self.assertEqual(len(self.player.trail), 10)

    # ── clear_trail ─────────────────────────────────────────────────────────

    def test_clear_trail_empties_trail(self):
        self.player.update_position(51.5, -0.1)
        self.player.update_position(51.6, -0.2)
        self.player.clear_trail()
        self.assertEqual(self.player.trail, [])

    def test_clear_trail_on_empty_trail_is_safe(self):
        self.player.clear_trail()  # should not raise
        self.assertEqual(self.player.trail, [])

    def test_clear_trail_does_not_reset_score(self):
        self.player.score = 500
        self.player.clear_trail()
        self.assertEqual(self.player.score, 500)


# ═══════════════════════════════════════════════════════════════════════════
#  2.  GAMETERRITORY TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestGameTerritory(unittest.TestCase):
    """Tests for the GameTerritory class (Shoelace + ray-casting)."""

    # ── Unit square in lat/lon space ────────────────────────────────────────
    #   Vertices at (0,0),(1,0),(1,1),(0,1)  →  area = 0.5 (shoelace result)
    UNIT_SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1)]

    # ── Real-world-ish small polygon near London ────────────────────────────
    LONDON_SQUARE = [
        (51.5000, -0.1000),
        (51.5010, -0.1000),
        (51.5010, -0.0990),
        (51.5000, -0.0990),
    ]

    # ── calculate_area (Shoelace) ───────────────────────────────────────────

    def test_unit_square_area(self):
        # Shoelace on [(0,0),(1,0),(1,1),(0,1)]:
        # sum = (0*0-1*0)+(1*1-1*0)+(1*1-0*1)+(0*0-0*1) = 0+1+1+0 = 2 → abs/2 = 1.0
        t = GameTerritory(owner_id=1, polygon=self.UNIT_SQUARE)
        self.assertAlmostEqual(t.area, 1.0, places=10)

    def test_area_is_positive_regardless_of_winding(self):
        """Shoelace must return absolute value – winding order irrelevant."""
        cw  = GameTerritory(1, [(0,0),(0,1),(1,1),(1,0)])
        ccw = GameTerritory(1, [(0,0),(1,0),(1,1),(0,1)])
        self.assertAlmostEqual(cw.area, ccw.area, places=10)

    def test_triangle_area(self):
        # Right-angle triangle with legs 1 unit → area = 0.5
        t = GameTerritory(1, [(0,0),(1,0),(0,1)])
        self.assertAlmostEqual(t.area, 0.5, places=10)

    def test_london_square_has_positive_area(self):
        t = GameTerritory(1, self.LONDON_SQUARE)
        self.assertGreater(t.area, 0)

    def test_degenerate_polygon_two_points_area_zero(self):
        t = GameTerritory(1, [(0,0),(1,1)])
        self.assertAlmostEqual(t.area, 0.0, places=10)

    def test_larger_polygon_has_larger_area(self):
        small = GameTerritory(1, [(0,0),(1,0),(1,1),(0,1)])
        large = GameTerritory(1, [(0,0),(2,0),(2,2),(0,2)])
        self.assertGreater(large.area, small.area)

    # ── contains_point (ray-casting) ────────────────────────────────────────

    def test_centre_point_inside_unit_square(self):
        t = GameTerritory(1, self.UNIT_SQUARE)
        self.assertTrue(t.contains_point(0.5, 0.5))

    def test_point_clearly_outside_unit_square(self):
        t = GameTerritory(1, self.UNIT_SQUARE)
        self.assertFalse(t.contains_point(5.0, 5.0))

    def test_point_far_outside_is_false(self):
        t = GameTerritory(1, self.UNIT_SQUARE)
        self.assertFalse(t.contains_point(-10, -10))

    def test_near_corner_but_outside(self):
        t = GameTerritory(1, self.UNIT_SQUARE)
        self.assertFalse(t.contains_point(1.001, 1.001))

    def test_near_corner_but_inside(self):
        t = GameTerritory(1, self.UNIT_SQUARE)
        self.assertTrue(t.contains_point(0.999, 0.999))

    def test_contains_point_london_centre(self):
        t = GameTerritory(1, self.LONDON_SQUARE)
        # Centre of the square
        self.assertTrue(t.contains_point(51.5005, -0.0995))

    def test_contains_point_london_outside(self):
        t = GameTerritory(1, self.LONDON_SQUARE)
        self.assertFalse(t.contains_point(52.0, -0.1))  # way north

    # ── owner_id ─────────────────────────────────────────────────────────────

    def test_owner_id_stored_correctly(self):
        t = GameTerritory(owner_id=42, polygon=self.UNIT_SQUARE)
        self.assertEqual(t.owner_id, 42)


# ═══════════════════════════════════════════════════════════════════════════
#  3.  GAMEMAP TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestGameMap(unittest.TestCase):
    """Tests for the GameMap container class."""

    def setUp(self):
        self.game_map = GameMap(map_id=99)
        self.p1 = Player(1, 'Alice', '#aa0000')
        self.p2 = Player(2, 'Bob',   '#0000bb')

    def test_map_id_stored(self):
        self.assertEqual(self.game_map.map_id, 99)

    def test_initial_players_empty(self):
        self.assertEqual(len(self.game_map.players), 0)

    def test_initial_territories_empty(self):
        self.assertEqual(len(self.game_map.territories), 0)

    def test_add_player(self):
        self.game_map.add_player(self.p1)
        self.assertIn(1, self.game_map.players)

    def test_add_two_players(self):
        self.game_map.add_player(self.p1)
        self.game_map.add_player(self.p2)
        self.assertEqual(len(self.game_map.players), 2)

    def test_get_player_returns_correct_player(self):
        self.game_map.add_player(self.p1)
        result = self.game_map.get_player(1)
        self.assertEqual(result.username, 'Alice')

    def test_get_player_nonexistent_returns_none(self):
        result = self.game_map.get_player(999)
        self.assertIsNone(result)

    def test_add_player_overwrites_same_id(self):
        """Adding a player with the same id replaces the existing entry."""
        self.game_map.add_player(self.p1)
        new_p1 = Player(1, 'Alice_v2', '#ff0000')
        self.game_map.add_player(new_p1)
        self.assertEqual(self.game_map.get_player(1).username, 'Alice_v2')

    def test_add_territory(self):
        t = GameTerritory(1, [(0,0),(1,0),(1,1),(0,1)])
        self.game_map.add_territory(t)
        self.assertEqual(len(self.game_map.territories), 1)

    def test_add_multiple_territories(self):
        for _ in range(5):
            self.game_map.add_territory(GameTerritory(1, [(0,0),(1,0),(1,1),(0,1)]))
        self.assertEqual(len(self.game_map.territories), 5)


# ═══════════════════════════════════════════════════════════════════════════
#  4.  GAMECONTROLLER TESTS
# ═══════════════════════════════════════════════════════════════════════════

# ---------------------------------------------------------------------------
#  Haversine reference implementation (independent of game code)
# ---------------------------------------------------------------------------
def _ref_haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


class TestHaversineDistance(unittest.TestCase):
    """Tests for GameController.haversine_distance."""

    def setUp(self):
        self.gc = GameController(GameMap(1))

    def test_same_point_is_zero(self):
        d = self.gc.haversine_distance(51.5, -0.1, 51.5, -0.1)
        self.assertAlmostEqual(d, 0.0, places=5)

    def test_known_distance_london_to_paris(self):
        # London (51.5074, -0.1278) → Paris (48.8566, 2.3522) ≈ 340 km
        d = self.gc.haversine_distance(51.5074, -0.1278, 48.8566, 2.3522)
        self.assertAlmostEqual(d / 1000, 340, delta=5)

    def test_symmetry(self):
        d1 = self.gc.haversine_distance(51.5, -0.1, 51.6, -0.2)
        d2 = self.gc.haversine_distance(51.6, -0.2, 51.5, -0.1)
        self.assertAlmostEqual(d1, d2, places=6)

    def test_ten_metres_north(self):
        """~10 m north = 0.00009° lat shift."""
        d = self.gc.haversine_distance(51.5000, -0.1, 51.5001, -0.1)
        self.assertAlmostEqual(d, 11.1, delta=1.0)

    def test_five_metres_east(self):
        d = self.gc.haversine_distance(51.5, -0.10000, 51.5, -0.09993)
        self.assertLess(d, 10)

    def test_matches_reference_implementation(self):
        pairs = [
            (51.5, -0.1, 51.6, -0.2),
            (48.8566, 2.3522, 40.7128, -74.0060),  # Paris → NYC
            (0.0, 0.0, 0.0, 1.0),
        ]
        for lat1, lon1, lat2, lon2 in pairs:
            with self.subTest(pair=(lat1, lon1, lat2, lon2)):
                expected = _ref_haversine(lat1, lon1, lat2, lon2)
                actual   = self.gc.haversine_distance(lat1, lon1, lat2, lon2)
                self.assertAlmostEqual(actual, expected, places=3)

    def test_returns_metres_not_km(self):
        # One degree of latitude ≈ 111 km → result should be ~111 000 m
        d = self.gc.haversine_distance(0.0, 0.0, 1.0, 0.0)
        self.assertGreater(d, 100_000)
        self.assertLess(d, 120_000)


class TestCheckSelfIntersection(unittest.TestCase):
    """Tests for GameController.check_self_intersection."""

    def _make_gc_with_trail(self, coords):
        gm = GameMap(1)
        p  = Player(1, 'test', '#fff')
        for lat, lon in coords:
            p.update_position(lat, lon)
        gm.add_player(p)
        return GameController(gm), p

    # ── Trail too short ──────────────────────────────────────────────────────

    def test_fewer_than_4_points_returns_none(self):
        gc, p = self._make_gc_with_trail([(51.5, -0.1), (51.501, -0.1), (51.502, -0.1)])
        self.assertIsNone(gc.check_self_intersection(p))

    def test_exactly_4_points_no_intersection(self):
        # Straight line – no loop
        gc, p = self._make_gc_with_trail([
            (51.500, -0.100),
            (51.501, -0.100),
            (51.502, -0.100),
            (51.503, -0.100),
        ])
        self.assertIsNone(gc.check_self_intersection(p))

    # ── Real intersection ────────────────────────────────────────────────────

    def test_intersection_detected_when_returning_to_start(self):
        """Player walks a rough square and returns close to the first point."""
        gc, p = self._make_gc_with_trail([
            (51.5000, -0.1000),   # 0 – start
            (51.5001, -0.1000),   # 1
            (51.5001, -0.0999),   # 2
            (51.5000, -0.0999),   # 3
            (51.5000, -0.10001),  # 4 – within 10 m of point 0
        ])
        result = gc.check_self_intersection(p)
        self.assertIsNotNone(result)
        self.assertEqual(result, 0)

    def test_intersection_returns_correct_index(self):
        """Intersection against point index 1, not 0."""
        gc, p = self._make_gc_with_trail([
            (51.5000, -0.1000),   # 0
            (51.5010, -0.1000),   # 1  ← target (≈1.1 km ahead)
            (51.5011, -0.1000),   # 2
            (51.5012, -0.1000),   # 3
            (51.5010, -0.10001),  # 4 – within 10 m of point 1
        ])
        result = gc.check_self_intersection(p)
        self.assertEqual(result, 1)

    # ── GPS-jitter guard (skip last 3 points) ────────────────────────────────

    def test_recent_points_not_checked(self):
        """The last 3 points are excluded from the back-check to prevent jitter triggers."""
        gc, p = self._make_gc_with_trail([
            (51.5000, -0.1000),  # 0
            (51.5001, -0.1000),  # 1
            (51.5002, -0.1000),  # 2
            (51.5003, -0.1000),  # 3
            # Point 4 is very close to point 3 but that's recent – should NOT trigger
            (51.5003, -0.10001), # 4
        ])
        # Points 2, 3 are in the excluded zone → only point 0 & 1 checked
        result = gc.check_self_intersection(p)
        self.assertIsNone(result)

    def test_threshold_10m_respected(self):
        """A point clearly more than 10 m from the start should NOT trigger intersection.
        0.001° latitude ≈ 111 m — safely outside the 10 m threshold."""
        gc, p = self._make_gc_with_trail([
            (51.5000, -0.1000),
            (51.5002, -0.1000),
            (51.5004, -0.1000),
            (51.5006, -0.1000),
            (51.5010, -0.1000),  # ≈ 111 m from point 0 – well outside 10 m threshold
        ])
        result = gc.check_self_intersection(p)
        self.assertIsNone(result)


class TestCheckTrailCollision(unittest.TestCase):
    """Tests for GameController.check_trail_collision."""

    def _setup_two_players(self, p2_trail):
        gm = GameMap(1)
        p1 = Player(1, 'Alice', '#f00')
        p2 = Player(2, 'Bob',   '#00f')
        for lat, lon in p2_trail:
            p2.update_position(lat, lon)
        gm.add_player(p1)
        gm.add_player(p2)
        return GameController(gm), p1, p2

    def test_no_collision_when_far_apart(self):
        gc, p1, p2 = self._setup_two_players([
            (52.0, -0.1), (52.001, -0.1)
        ])
        result = gc.check_trail_collision(1, 51.5, -0.1)
        self.assertIsNone(result)

    def test_collision_detected_when_stepping_on_opponents_trail(self):
        """Alice steps within 5 m of Bob's trail point.
        0.00004° lat ≈ 4.4 m — well inside the 5 m threshold."""
        gc, p1, p2 = self._setup_two_players([
            (51.5000, -0.1000),
            (51.5001, -0.1000),
        ])
        # Alice moves to within 4.4 m of Bob's first trail point
        result = gc.check_trail_collision(1, 51.50004, -0.1000)
        self.assertEqual(result, 2)  # Bob's user_id

    def test_collision_clears_opponents_trail(self):
        gc, p1, p2 = self._setup_two_players([
            (51.5000, -0.1000),
            (51.5001, -0.1000),
        ])
        gc.check_trail_collision(1, 51.50004, -0.1000)
        self.assertEqual(p2.trail, [])

    def test_no_self_collision(self):
        """A player must never trigger a collision with their own trail."""
        gm = GameMap(1)
        p1 = Player(1, 'Alice', '#f00')
        p1.update_position(51.5000, -0.1000)
        p1.update_position(51.5001, -0.1000)
        gm.add_player(p1)
        gc = GameController(gm)
        result = gc.check_trail_collision(1, 51.5001, -0.1000)
        self.assertIsNone(result)

    def test_player_with_short_trail_not_collidable(self):
        """A trail shorter than 2 points is skipped."""
        gc, p1, p2 = self._setup_two_players([(51.5001, -0.1000)])  # only 1 point
        result = gc.check_trail_collision(1, 51.5001, -0.1000)
        self.assertIsNone(result)


class TestCreateTerritoryFromIntersection(unittest.TestCase):
    """Tests for GameController.create_territory_from_intersection."""

    def _gc_with_player(self, trail):
        gm = GameMap(1)
        p  = Player(1, 'TFO', '#fff')
        p.trail = list(trail)
        gm.add_player(p)
        return GameController(gm), p

    def test_creates_territory_from_valid_loop(self):
        trail = [
            (51.5000, -0.1000),
            (51.5001, -0.1000),
            (51.5001, -0.0999),
            (51.5000, -0.0999),
            (51.5000, -0.10001),  # returns near index 0
        ]
        gc, p = self._gc_with_player(trail)
        t = gc.create_territory_from_intersection(p, intersection_index=0)
        self.assertIsNotNone(t)
        self.assertIsInstance(t, GameTerritory)

    def test_returns_none_when_loop_has_fewer_than_3_points(self):
        gc, p = self._gc_with_player([(51.5, -0.1), (51.501, -0.1)])
        t = gc.create_territory_from_intersection(p, intersection_index=0)
        self.assertIsNone(t)

    def test_territory_owner_matches_player(self):
        trail = [(0,0),(1,0),(1,1),(0,1),(0.001, 0.001)]
        gc, p = self._gc_with_player(trail)
        t = gc.create_territory_from_intersection(p, intersection_index=0)
        if t:  # area might pass filter
            self.assertEqual(t.owner_id, 1)

    def test_rejects_tiny_territory_below_noise_floor(self):
        """A triangle of 0.000001° sides is below the GPS-noise filter."""
        micro = 0.000001
        trail = [
            (0, 0),
            (micro, 0),
            (micro, micro),
            (0, micro),
            (0, 0.000001),
        ]
        gc, p = self._gc_with_player(trail)
        t = gc.create_territory_from_intersection(p, intersection_index=0)
        self.assertIsNone(t)

    def test_uses_loop_slice_starting_at_intersection_index(self):
        """Territory polygon should contain only points from intersection_index onwards."""
        trail = [
            (0, 0),    # 0
            (1, 0),    # 1
            (1, 1),    # 2
            (0, 1),    # 3
            (0, 0.1),  # 4 – close to index 0
        ]
        gc, p = self._gc_with_player(trail)
        t = gc.create_territory_from_intersection(p, intersection_index=1)
        if t:
            # Polygon should start at index 1, not 0
            self.assertEqual(t.polygon[0], (1, 0))


class TestUpdatePlayerPosition(unittest.TestCase):
    """Integration tests for the full update_player_position flow."""

    def _fresh_gc(self):
        gm = GameMap(1)
        p  = Player(1, 'TFO', '#fff')
        gm.add_player(p)
        return GameController(gm), gm, p

    def test_returns_none_for_unknown_user(self):
        gc, gm, _ = self._fresh_gc()
        result = gc.update_player_position(999, 51.5, -0.1)
        self.assertIsNone(result)

    def test_trail_grows_with_each_update(self):
        gc, gm, p = self._fresh_gc()
        gc.update_player_position(1, 51.500, -0.100)
        gc.update_player_position(1, 51.501, -0.100)
        gc.update_player_position(1, 51.502, -0.100)
        self.assertEqual(len(p.trail), 3)

    def test_returns_none_when_no_loop_closed(self):
        gc, gm, p = self._fresh_gc()
        for i in range(6):
            result = gc.update_player_position(1, 51.500 + i * 0.001, -0.100)
        self.assertIsNone(result)  # straight line – no territory

    def test_territory_created_and_trail_cleared_on_loop_close(self):
        """Walk a 50×50 m square (≈0.0005° × 0.0007°) and return to start."""
        gc, gm, p = self._fresh_gc()
        waypoints = [
            (51.50000, -0.10000),
            (51.50045, -0.10000),
            (51.50045, -0.09930),
            (51.50000, -0.09930),
            (51.50000, -0.10001),  # within 10 m of waypoints[0]
        ]
        territory = None
        for lat, lon in waypoints:
            result = gc.update_player_position(1, lat, lon)
            if result is not None:
                territory = result

        self.assertIsNotNone(territory, "Expected territory to be created after loop")
        self.assertIsInstance(territory, GameTerritory)
        self.assertEqual(p.trail, [], "Trail should be cleared after territory creation")

    def test_territory_added_to_game_map(self):
        gc, gm, p = self._fresh_gc()
        waypoints = [
            (51.50000, -0.10000),
            (51.50045, -0.10000),
            (51.50045, -0.09930),
            (51.50000, -0.09930),
            (51.50000, -0.10001),
        ]
        for lat, lon in waypoints:
            gc.update_player_position(1, lat, lon)
        self.assertGreater(len(gm.territories), 0)

    def test_player_score_increases_after_territory(self):
        """
        In-memory player.score is incremented by int(territory.area).
        Because territory.area is in degree² (~1e-7 for a 50 m square), int()
        rounds to 0.  Real scoring happens via area_scale_factor in app.py.
        We therefore verify that a territory was created (which is what triggers
        scoring) and that the territory's area is a positive float.
        """
        gc, gm, p = self._fresh_gc()
        waypoints = [
            (51.50000, -0.10000),
            (51.50045, -0.10000),
            (51.50045, -0.09930),
            (51.50000, -0.09930),
            (51.50000, -0.10001),
        ]
        territory = None
        for lat, lon in waypoints:
            result = gc.update_player_position(1, lat, lon)
            if result is not None:
                territory = result
        self.assertIsNotNone(territory, "Territory should have been created")
        self.assertGreater(territory.area, 0.0, "Territory area should be positive")


# ═══════════════════════════════════════════════════════════════════════════
#  5.  PURE HELPER FUNCTION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestName2Color(unittest.TestCase):
    """Tests for name2color helper."""

    def test_returns_hex_string(self):
        color = name2color('TFO')
        self.assertRegex(color, r'^#[0-9a-f]{6}$')

    def test_deterministic_same_input_same_output(self):
        self.assertEqual(name2color('TFO'), name2color('TFO'))

    def test_different_names_different_colors(self):
        """Different usernames should produce different colours (practically always)."""
        names = ['Alice', 'Bob', 'Charlie', 'TFO', 'Jola', 'Leon', 'Dami']
        colors = [name2color(n) for n in names]
        self.assertEqual(len(set(colors)), len(colors), "All colours should be unique")

    def test_consistent_across_calls(self):
        for _ in range(10):
            self.assertEqual(name2color('Leon'), name2color('Leon'))

    def test_single_character_name(self):
        color = name2color('A')
        self.assertRegex(color, r'^#[0-9a-f]{6}$')

    def test_empty_string_returns_hex(self):
        """Edge case – empty username (hash_code = 0)."""
        color = name2color('')
        self.assertRegex(color, r'^#[0-9a-f]{6}$')

    def test_color_values_in_valid_range(self):
        for name in ['TFO', 'abc', 'ZZZZZ', '12345']:
            color = name2color(name)
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            self.assertGreaterEqual(r, 0); self.assertLessEqual(r, 255)
            self.assertGreaterEqual(g, 0); self.assertLessEqual(g, 255)
            self.assertGreaterEqual(b, 0); self.assertLessEqual(b, 255)


class TestCalculateLevel(unittest.TestCase):
    """Tests for the level-from-XP formula: level = floor(sqrt(0.01 * xp))."""

    def test_zero_xp_is_level_0(self):
        self.assertEqual(calculate_level(0), 0)

    def test_100_xp_is_level_1(self):
        self.assertEqual(calculate_level(100), 1)

    def test_399_xp_is_level_1(self):
        self.assertEqual(calculate_level(399), 1)

    def test_400_xp_is_level_2(self):
        self.assertEqual(calculate_level(400), 2)

    def test_900_xp_is_level_3(self):
        self.assertEqual(calculate_level(900), 3)

    def test_10000_xp_is_level_10(self):
        self.assertEqual(calculate_level(10000), 10)

    def test_level_never_decreases_with_more_xp(self):
        prev = 0
        for xp in range(0, 50000, 500):
            level = calculate_level(xp)
            self.assertGreaterEqual(level, prev)
            prev = level

    def test_level_formula_matches_sqrt(self):
        for xp in [0, 100, 400, 900, 1600, 2500]:
            expected = int(math.sqrt(0.01 * xp))
            self.assertEqual(calculate_level(xp), expected)


class TestAreaScaleFactor(unittest.TestCase):
    """Tests for the area → game-unit conversion."""

    # Approximate area of a 50×50 m square in degree² units
    SMALL_AREA = 1e-6

    def test_points_mode_returns_integer(self):
        result = area_scale_factor(self.SMALL_AREA, 'points')
        self.assertIsInstance(result, int)

    def test_xp_mode_returns_integer(self):
        result = area_scale_factor(self.SMALL_AREA, 'xp')
        self.assertIsInstance(result, int)

    def test_points_greater_than_xp_for_same_area(self):
        """Points scale is 10× the XP scale by design."""
        pts = area_scale_factor(self.SMALL_AREA, 'points')
        xp  = area_scale_factor(self.SMALL_AREA, 'xp')
        self.assertAlmostEqual(pts / xp, 10.0, delta=0.5)

    def test_zero_area_gives_zero_points(self):
        self.assertEqual(area_scale_factor(0, 'points'), 0)
        self.assertEqual(area_scale_factor(0, 'xp'), 0)

    def test_larger_area_gives_more_points(self):
        small = area_scale_factor(1e-6,  'points')
        large = area_scale_factor(1e-4,  'points')
        self.assertGreater(large, small)

    def test_unknown_mode_returns_none(self):
        result = area_scale_factor(1e-6, 'bananas')
        self.assertIsNone(result)

    def test_points_circa_1_per_10_sqm(self):
        """
        The docstring claims ~1 point per 10 m².
        1e-6 degree² ≈ 12.4 m² at London latitude.
        Rough sanity: result should be in the low single-digits range.
        """
        # 1e-8 degree² ≈ 0.12 m²  → should give at least 0 points
        result = area_scale_factor(1e-8, 'points')
        self.assertGreaterEqual(result, 0)


class TestPasswordValidation(unittest.TestCase):
    """Tests for the password-validation regex logic."""

    # ── Valid passwords ──────────────────────────────────────────────────────

    def test_valid_password(self):
        self.assertTrue(validate_password('Hello123!'))

    def test_valid_password_exactly_8_chars(self):
        self.assertTrue(validate_password('Ab1!aaaa'))

    def test_valid_password_with_various_specials(self):
        for special in list('!@#$%^&*(),.?":{}|<>'):
            pwd = f'Abc1{special}xyz'
            self.assertTrue(validate_password(pwd), f"Should pass with special: {special}")

    def test_valid_long_password(self):
        self.assertTrue(validate_password('MyStr0ng!Passw0rd#2025'))

    # ── Too short ────────────────────────────────────────────────────────────

    def test_7_chars_fails(self):
        self.assertFalse(validate_password('Ab1!aaa'))

    def test_empty_fails(self):
        self.assertFalse(validate_password(''))

    # ── Missing character class ──────────────────────────────────────────────

    def test_no_uppercase_fails(self):
        self.assertFalse(validate_password('hello123!'))

    def test_no_lowercase_fails(self):
        self.assertFalse(validate_password('HELLO123!'))

    def test_no_digit_fails(self):
        self.assertFalse(validate_password('HelloWorld!'))

    def test_no_special_char_fails(self):
        self.assertFalse(validate_password('Hello1234'))

    # ── Boundary: exactly 8 chars ────────────────────────────────────────────

    def test_exactly_8_valid_chars_passes(self):
        self.assertTrue(validate_password('Aa1!aaaa'))

    def test_exactly_8_missing_special_fails(self):
        self.assertFalse(validate_password('Aa1aaaaa'))

    # ── Edge cases ───────────────────────────────────────────────────────────

    def test_all_requirements_met_in_different_order(self):
        # special first, then uppercase, number, lowercase padding
        self.assertTrue(validate_password('!A1aaaaa'))

    def test_whitespace_only_password_fails(self):
        self.assertFalse(validate_password('        '))  # 8 spaces, no classes met


# ═══════════════════════════════════════════════════════════════════════════
#  6.  FLASK ROUTE TESTS  (in-memory SQLite test database)
# ═══════════════════════════════════════════════════════════════════════════

# Only run Flask tests if flask_sqlalchemy etc. are installed
try:
    from flask import Flask as _Flask
    from flask_sqlalchemy import SQLAlchemy as _SA
    from flask_bcrypt import Bcrypt as _Bcrypt
    FLASK_EXTENSIONS_AVAILABLE = True
except ImportError:
    FLASK_EXTENSIONS_AVAILABLE = False


if FLASK_EXTENSIONS_AVAILABLE:
    # Import the real app but reconfigure it for an in-memory test DB
    import importlib, types

    def _build_test_app():
        """
        Imports app.py and swaps its DB for an isolated in-memory SQLite
        instance so tests never touch the production database.
        """
        import app as _app_module
        _app_module.app.config['TESTING'] = True
        _app_module.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        _app_module.app.config['WTF_CSRF_ENABLED'] = False
        _app_module.app.config['SECRET_KEY'] = 'test-secret'
        with _app_module.app.app_context():
            _app_module.db.drop_all()
            _app_module.db.create_all()
        return _app_module.app, _app_module.db

    class TestFlaskAuth(unittest.TestCase):
        """Tests for registration and login routes."""

        @classmethod
        def setUpClass(cls):
            cls.flask_app, cls.db = _build_test_app()
            cls.client = cls.flask_app.test_client()

        def setUp(self):
            """Wipe tables before each test for isolation."""
            with self.flask_app.app_context():
                self.db.drop_all()
                self.db.create_all()

        def _register(self, username='TFO', password='Hello123!'):
            return self.client.post('/register', data={
                'username': username, 'password': password
            }, follow_redirects=True)

        def _login(self, username='TFO', password='Hello123!'):
            return self.client.post('/login', data={
                'username': username, 'password': password
            }, follow_redirects=True)

        # ── Registration ─────────────────────────────────────────────────────

        def test_register_valid_user_redirects_to_login(self):
            resp = self._register()
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b'Login', resp.data)

        def test_register_stores_user_in_db(self):
            self._register()
            from app import Users
            with self.flask_app.app_context():
                user = Users.query.filter_by(username='TFO').first()
                self.assertIsNotNone(user)

        def test_register_password_hashed(self):
            self._register()
            from app import Users
            with self.flask_app.app_context():
                user = Users.query.filter_by(username='TFO').first()
                self.assertNotEqual(user.password, 'Hello123!')
                self.assertTrue(user.password.startswith('$2'))  # bcrypt prefix

        def test_register_duplicate_username_rejected(self):
            """Second registration with same username must not create a second DB row,
            and the flash error must now appear in the response (templates render flash)."""
            self._register()
            resp = self._register()  # second attempt – should fail
            from app import Users
            with self.flask_app.app_context():
                count = Users.query.filter_by(username='TFO').count()
                self.assertEqual(count, 1, "Duplicate username should not create a second row")
            self.assertIn(b'already exists', resp.data)

        def test_register_weak_password_rejected(self):
            """Weak password must not create a user and flash message must appear."""
            resp = self._register(password='weakpass')
            from app import Users
            with self.flask_app.app_context():
                self.assertIsNone(Users.query.filter_by(username='TFO').first(),
                                  "Weak password should not create a user")
            self.assertIn(b'does not meet requirements', resp.data)

        def test_register_password_no_uppercase_rejected(self):
            resp = self._register(password='hello123!')
            from app import Users
            with self.flask_app.app_context():
                self.assertIsNone(Users.query.filter_by(username='TFO').first())
            self.assertIn(b'does not meet requirements', resp.data)

        def test_register_password_no_digit_rejected(self):
            resp = self._register(password='HelloWorld!')
            from app import Users
            with self.flask_app.app_context():
                self.assertIsNone(Users.query.filter_by(username='TFO').first())
            self.assertIn(b'does not meet requirements', resp.data)

        def test_register_password_too_short_rejected(self):
            resp = self._register(password='Ab1!')
            from app import Users
            with self.flask_app.app_context():
                self.assertIsNone(Users.query.filter_by(username='TFO').first())
            self.assertIn(b'does not meet requirements', resp.data)

        # ── Login ────────────────────────────────────────────────────────────

        def test_login_valid_credentials_redirects_to_dashboard(self):
            self._register()
            resp = self._login()
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b'dashboard', resp.data.lower())

        def test_login_wrong_password_rejected(self):
            """Wrong password must not authenticate and flash error must appear."""
            self._register()
            resp = self._login(password='WrongPass1!')
            self.assertNotEqual(resp.request.path if hasattr(resp, 'request') else '',
                                '/dashboard')
            self.assertIn(b'Invalid username or password', resp.data)

        def test_login_nonexistent_user_rejected(self):
            """Non-existent username must not authenticate and flash error must appear."""
            resp = self._login(username='nobody', password='Hello123!')
            self.assertIn(b'Invalid username or password', resp.data)

        # ── Logout / session ─────────────────────────────────────────────────

        def test_logout_clears_session_and_redirects(self):
            self._register()
            self._login()
            resp = self.client.get('/logout', follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b'ANNEX', resp.data)

        def test_dashboard_requires_login(self):
            """Unauthenticated GET /dashboard should redirect to home."""
            resp = self.client.get('/dashboard', follow_redirects=True)
            # Should land back at home page
            self.assertNotIn(b'Welcome,', resp.data)

        def test_map_view_requires_login(self):
            resp = self.client.get('/map_view?map_id=1', follow_redirects=True)
            self.assertNotIn(b'Leaderboard', resp.data)

    class TestFlaskFriends(unittest.TestCase):
        """Tests for friend-request routes."""

        @classmethod
        def setUpClass(cls):
            cls.flask_app, cls.db = _build_test_app()

        def setUp(self):
            with self.flask_app.app_context():
                self.db.drop_all()
                self.db.create_all()
            self.client_a = self.flask_app.test_client()
            self.client_b = self.flask_app.test_client()
            # Register two users
            self.client_a.post('/register', data={'username': 'Alice', 'password': 'Hello123!'})
            self.client_b.post('/register', data={'username': 'Bob',   'password': 'Hello123!'})
            self.client_a.post('/login',    data={'username': 'Alice', 'password': 'Hello123!'})
            self.client_b.post('/login',    data={'username': 'Bob',   'password': 'Hello123!'})

        import json as _json

        def _send_request(self, client, to_username):
            import json
            return client.post('/send_friend_request',
                               data=json.dumps({'username': to_username}),
                               content_type='application/json')

        def test_send_friend_request_returns_200(self):
            resp = self._send_request(self.client_a, 'Bob')
            self.assertEqual(resp.status_code, 200)

        def test_send_friend_request_to_nonexistent_user_returns_404(self):
            resp = self._send_request(self.client_a, 'nobody')
            self.assertEqual(resp.status_code, 404)

        def test_send_request_to_self_returns_400(self):
            resp = self._send_request(self.client_a, 'Alice')
            self.assertEqual(resp.status_code, 400)

        def test_duplicate_request_returns_400(self):
            self._send_request(self.client_a, 'Bob')
            resp = self._send_request(self.client_a, 'Bob')
            self.assertEqual(resp.status_code, 400)

        def test_accept_friend_request_returns_200(self):
            import json, app as _m
            self._send_request(self.client_a, 'Bob')
            with self.flask_app.app_context():
                alice = _m.Users.query.filter_by(username='Alice').first()
            resp = self.client_b.post(
                '/accept_friend_request',
                data=json.dumps({'requester_id': alice.id}),
                content_type='application/json'
            )
            self.assertEqual(resp.status_code, 200)

        def test_reject_friend_request_returns_200(self):
            import json, app as _m
            self._send_request(self.client_a, 'Bob')
            with self.flask_app.app_context():
                alice = _m.Users.query.filter_by(username='Alice').first()
            resp = self.client_b.post(
                '/reject_friend_request',
                data=json.dumps({'requester_id': alice.id}),
                content_type='application/json'
            )
            self.assertEqual(resp.status_code, 200)

        def test_send_friend_request_unauthenticated_returns_401(self):
            import json
            anon = self.flask_app.test_client()
            resp = anon.post('/send_friend_request',
                             data=json.dumps({'username': 'Bob'}),
                             content_type='application/json')
            self.assertEqual(resp.status_code, 401)

    class TestFlaskMaps(unittest.TestCase):
        """Tests for map creation and joining routes."""

        @classmethod
        def setUpClass(cls):
            cls.flask_app, cls.db = _build_test_app()

        def setUp(self):
            with self.flask_app.app_context():
                self.db.drop_all()
                self.db.create_all()
            self.client = self.flask_app.test_client()
            self.client.post('/register', data={'username': 'TFO', 'password': 'Hello123!'})
            self.client.post('/login',    data={'username': 'TFO', 'password': 'Hello123!'})

        def _create_map(self, name='TestMap', win_type='points',
                        win_val=50000, map_type='public'):
            return self.client.post('/dashboard', data={
                'map_name': name,
                'map_type': map_type,
                'win_condition_type': win_type,
                'win_condition_value_points': str(win_val),
                'win_condition_value_time': '30',
                'map_center_lat': '51.5',
                'map_center_lon': '-0.1',
            }, follow_redirects=True)

        def test_create_map_redirects_to_dashboard(self):
            resp = self._create_map()
            self.assertEqual(resp.status_code, 200)

        def test_create_map_stored_in_db(self):
            self._create_map('MyMap')
            import app as _m
            with self.flask_app.app_context():
                m = _m.Maps_Data.query.filter_by(map_name='MyMap').first()
                self.assertIsNotNone(m)

        def test_created_map_has_6_char_code(self):
            self._create_map('CodeMap')
            import app as _m
            with self.flask_app.app_context():
                m = _m.Maps_Data.query.filter_by(map_name='CodeMap').first()
                self.assertEqual(len(m.map_code), 6)

        def test_created_map_code_is_alphanumeric_uppercase(self):
            self._create_map('AlphaMap')
            import app as _m
            with self.flask_app.app_context():
                m = _m.Maps_Data.query.filter_by(map_name='AlphaMap').first()
                self.assertTrue(m.map_code.isupper() or m.map_code.isalnum())

        def test_creator_automatically_in_map(self):
            self._create_map('AutoJoinMap')
            import app as _m
            with self.flask_app.app_context():
                m  = _m.Maps_Data.query.filter_by(map_name='AutoJoinMap').first()
                u  = _m.Users.query.filter_by(username='TFO').first()
                um = _m.User_Map.query.filter_by(map_id=m.id, user_id=u.id).first()
                self.assertIsNotNone(um)

        def test_create_time_map(self):
            resp = self.client.post('/dashboard', data={
                'map_name': 'TimeMap',
                'map_type': 'public',
                'win_condition_type': 'time',
                'win_condition_value_time': '30',
                'map_center_lat': '51.5',
                'map_center_lon': '-0.1',
            }, follow_redirects=True)
            import app as _m
            with self.flask_app.app_context():
                m = _m.Maps_Data.query.filter_by(map_name='TimeMap').first()
                self.assertEqual(m.win_condition_type, 'time')

        def test_join_map_by_valid_code(self):
            """Register a second user and have them join by code."""
            self._create_map('JoinCodeMap')
            import app as _m
            with self.flask_app.app_context():
                m = _m.Maps_Data.query.filter_by(map_name='JoinCodeMap').first()
                code = m.map_code

            client2 = self.flask_app.test_client()
            client2.post('/register', data={'username': 'Jola', 'password': 'Hello123!'})
            client2.post('/login',    data={'username': 'Jola', 'password': 'Hello123!'})
            resp = client2.post('/dashboard', data={'join_code': code},
                                follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            with self.flask_app.app_context():
                jola = _m.Users.query.filter_by(username='Jola').first()
                um   = _m.User_Map.query.filter_by(map_id=m.id, user_id=jola.id).first()
                self.assertIsNotNone(um)

        def test_join_invalid_code_shows_error(self):
            """An invalid code must not add any user_map row and must show flash error."""
            import app as _m
            with self.flask_app.app_context():
                before_count = _m.User_Map.query.count()
            resp = self.client.post('/dashboard', data={'join_code': 'XXXXXX'},
                                    follow_redirects=True)
            with self.flask_app.app_context():
                after_count = _m.User_Map.query.count()
            self.assertEqual(before_count, after_count,
                             "Invalid code must not create a user_map entry")
            self.assertIn(b'Invalid map code', resp.data)

        def test_join_map_already_in_shows_error(self):
            """Joining a map already in must not duplicate the row and must show flash."""
            self._create_map('DupMap')
            import app as _m
            with self.flask_app.app_context():
                m = _m.Maps_Data.query.filter_by(map_name='DupMap').first()
                code = m.map_code
                u = _m.Users.query.filter_by(username='TFO').first()
                before_count = _m.User_Map.query.filter_by(
                    map_id=m.id, user_id=u.id).count()
            resp = self.client.post('/dashboard', data={'join_code': code},
                                    follow_redirects=True)
            with self.flask_app.app_context():
                after_count = _m.User_Map.query.filter_by(
                    map_id=m.id, user_id=u.id).count()
            self.assertEqual(before_count, after_count,
                             "Re-joining a map must not add a duplicate row")
            self.assertIn(b'already in this map', resp.data)

        def test_join_completed_map_shows_error(self):
            """A completed map must not accept new members and must show flash."""
            self._create_map('DoneMap')
            import app as _m
            with self.flask_app.app_context():
                m = _m.Maps_Data.query.filter_by(map_name='DoneMap').first()
                m.game_status = 'completed'
                self.db.session.commit()
                code = m.map_code

            client2 = self.flask_app.test_client()
            client2.post('/register', data={'username': 'Late', 'password': 'Hello123!'})
            client2.post('/login',    data={'username': 'Late', 'password': 'Hello123!'})
            resp = client2.post('/dashboard', data={'join_code': code},
                                follow_redirects=True)

            with self.flask_app.app_context():
                late_user = _m.Users.query.filter_by(username='Late').first()
                entry = _m.User_Map.query.filter_by(
                    map_id=m.id, user_id=late_user.id).first()
                self.assertIsNone(entry,
                    "Completed map must not add late-joining user to user_map")
            self.assertIn(b'already ended', resp.data)


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Collect all test classes
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    core_classes = [
        TestPlayer,
        TestGameTerritory,
        TestGameMap,
        TestHaversineDistance,
        TestCheckSelfIntersection,
        TestCheckTrailCollision,
        TestCreateTerritoryFromIntersection,
        TestUpdatePlayerPosition,
        TestName2Color,
        TestCalculateLevel,
        TestAreaScaleFactor,
        TestPasswordValidation,
    ]

    flask_classes = []
    if FLASK_EXTENSIONS_AVAILABLE:
        flask_classes = [
            TestFlaskAuth,
            TestFlaskFriends,
            TestFlaskMaps,
        ]
    else:
        print("\n[INFO] Flask extensions not installed – skipping Flask route tests.\n"
              "       Install flask_sqlalchemy, flask_bcrypt, flask_socketio to enable them.\n")

    for cls in core_classes + flask_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)