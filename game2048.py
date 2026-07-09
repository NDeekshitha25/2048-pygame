"""
2048 - Pygame Edition
=====================

A single-file, object-oriented implementation of the classic 2048 puzzle game.

Features:
    - Explicit move_left / move_right / move_up / move_down logic on real
      Tile objects (no board rotation tricks anywhere).
    - Smooth slide, merge-pop, and spawn animations driven by a virtual,
      pausable delta-time clock.
    - Unlimited undo via a move history stack.
    - Pause, mute, and restart controls.
    - Persistent statistics and settings stored in a JSON file that is
      created automatically the first time the game runs.
    - Procedurally generated sound effects - no external asset files needed.

Controls:
    Arrow keys / WASD  - move tiles
    U                  - undo last move
    R                  - restart
    P                  - pause / resume
    M                  - mute / unmute sound
    ESC                - quit

Run with:  python game2048.py
Requires:  Python 3.10+, pygame 2.x, numpy
"""

from __future__ import annotations

import colorsys
import itertools
import json
import math
import os
import random
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

import numpy as np
import pygame


# ======================================================================
# Constants
# ======================================================================

BOARD_SIZE = 4                  # number of rows/columns
TILE_PIXELS = 100                # size of a single tile in pixels
TILE_GAP = 8                     # gap between tiles and around the board
TOP_BAR_HEIGHT = 110              # space reserved for score/stats/hints

BOARD_PIXELS = BOARD_SIZE * TILE_PIXELS + (BOARD_SIZE + 1) * TILE_GAP
WINDOW_WIDTH = BOARD_PIXELS
WINDOW_HEIGHT = BOARD_PIXELS + TOP_BAR_HEIGHT

FPS = 60
WINDOW_TITLE = "2048"

SLIDE_DURATION = 0.12             # seconds for a tile to slide into place
SPAWN_DURATION = 0.15             # seconds for a new tile to scale in
POP_DURATION = 0.12               # seconds for the merge "pop" bounce
POP_SCALE_BUMP = 0.18             # how much a merged tile bulges when it pops

DATA_FILE = "game2048_data.json"  # stats + settings, created if missing

BASE_TILE_COLORS: Dict[int, Tuple[int, int, int]] = {
    0: (205, 193, 180),
    2: (238, 228, 218),
    4: (237, 224, 200),
    8: (242, 177, 121),
    16: (245, 149, 99),
    32: (246, 124, 95),
    64: (246, 94, 59),
    128: (237, 207, 114),
    256: (237, 204, 97),
    512: (237, 200, 80),
    1024: (237, 197, 63),
    2048: (237, 194, 46),
}

BACKGROUND_COLOR = (250, 248, 239)
BOARD_BACKGROUND_COLOR = (187, 173, 160)
DARK_TEXT_COLOR = (119, 110, 101)
LIGHT_TEXT_COLOR = (249, 246, 242)


# ======================================================================
# Small helper functions (pure, stateless)
# ======================================================================

def ease_out_cubic(t: float) -> float:
    """Decelerating easing curve so slides feel natural instead of linear."""
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def lerp(start: float, end: float, t: float) -> float:
    """Linear interpolation between start and end at position t (0..1)."""
    return start + (end - start) * t


def get_tile_color(value: int) -> Tuple[int, int, int]:
    """Return a color for a tile value, generating one procedurally for
    values beyond 2048 so the game doesn't break once players go further."""
    if value in BASE_TILE_COLORS:
        return BASE_TILE_COLORS[value]
    exponent = int(math.log2(value)) if value > 0 else 0
    hue = (exponent * 27 % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.85)
    return int(r * 255), int(g * 255), int(b * 255)


def get_text_color(value: int) -> Tuple[int, int, int]:
    """Small values sit on light tiles and need dark text; the rest need light text."""
    return DARK_TEXT_COLOR if value <= 4 else LIGHT_TEXT_COLOR


def generate_tone(frequency: float, duration: float, volume: float = 0.3) -> pygame.mixer.Sound:
    """Procedurally generate a short sine-wave beep as a pygame Sound.

    This avoids shipping or loading any external audio files: the waveform
    is built directly with numpy and handed to pygame's sound array API.
    """
    sample_rate = 44100
    sample_count = int(sample_rate * duration)
    t = np.linspace(0, duration, sample_count, endpoint=False)
    wave = np.sin(2 * np.pi * frequency * t)
    fade_out = np.linspace(1.0, 0.0, sample_count) ** 2  # avoid an audible click at the tail
    audio = (wave * fade_out * 32767 * volume).astype(np.int16)
    stereo = np.column_stack((audio, audio))
    return pygame.sndarray.make_sound(np.ascontiguousarray(stereo))


# ======================================================================
# Direction
# ======================================================================

class Direction(Enum):
    LEFT = auto()
    RIGHT = auto()
    UP = auto()
    DOWN = auto()


# ======================================================================
# Tile
# ======================================================================

class Tile:
    """A single numbered tile living on the board.

    A Tile carries a bit of animation-related state (where it slid from,
    whether it just spawned, whether it just merged) so the renderer can
    animate it smoothly without the board's move logic needing to know
    anything about pixels or timing.
    """

    _next_id = itertools.count()

    def __init__(self, value: int, row: int, col: int):
        self.id: int = next(Tile._next_id)
        self.value: int = value
        self.row: int = row
        self.col: int = col

        # Animation bookkeeping, populated by the Game class around moves.
        self.anim_start_row: float = float(row)
        self.anim_start_col: float = float(col)
        self.move_start_time: float = 0.0
        self.spawn_time: float = 0.0
        self.just_spawned: bool = True
        self.merged: bool = False


# ======================================================================
# Board - pure game logic, no rendering/timing/persistence
# ======================================================================

class Board:
    """Holds the grid of tiles and the rules for moving them.

    Every move method (move_left / move_right / move_up / move_down) works
    by grouping tiles into the relevant rows or columns and sliding/merging
    them directly along that axis. No matrix rotation is used anywhere -
    each direction has its own explicit, readable code path.
    """

    def __init__(self, size: int = BOARD_SIZE):
        self.size = size
        self.tiles: List[Tile] = []

    def reset(self) -> None:
        """Clear the board and spawn the two starting tiles."""
        self.tiles = []
        self.spawn_tile()
        self.spawn_tile()

    def empty_cells(self) -> List[Tuple[int, int]]:
        """Return every (row, col) coordinate that currently has no tile."""
        occupied = {(t.row, t.col) for t in self.tiles}
        return [
            (r, c)
            for r in range(self.size)
            for c in range(self.size)
            if (r, c) not in occupied
        ]

    def spawn_tile(self) -> Optional[Tile]:
        """Place a new tile (90% a 2, 10% a 4) on a random empty cell."""
        empties = self.empty_cells()
        if not empties:
            return None
        row, col = random.choice(empties)
        value = 2 if random.random() < 0.9 else 4
        tile = Tile(value, row, col)
        self.tiles.append(tile)
        return tile

    def clear_transient_flags(self) -> None:
        """Reset per-move animation flags right before a new move is attempted."""
        for tile in self.tiles:
            tile.merged = False
            tile.anim_start_row = float(tile.row)
            tile.anim_start_col = float(tile.col)

    # ------------------------------------------------------------------
    # Explicit movement methods
    # ------------------------------------------------------------------

    def move_left(self) -> Tuple[bool, int]:
        """Slide and merge every row toward column 0."""
        return self._slide_rows(towards_start=True)

    def move_right(self) -> Tuple[bool, int]:
        """Slide and merge every row toward the last column."""
        return self._slide_rows(towards_start=False)

    def move_up(self) -> Tuple[bool, int]:
        """Slide and merge every column toward row 0."""
        return self._slide_columns(towards_start=True)

    def move_down(self) -> Tuple[bool, int]:
        """Slide and merge every column toward the last row."""
        return self._slide_columns(towards_start=False)

    def _slide_rows(self, towards_start: bool) -> Tuple[bool, int]:
        moved_any = False
        score_gained = 0
        to_remove: List[Tile] = []
        for row in range(self.size):
            line = [t for t in self.tiles if t.row == row]
            gained, moved, removed = self._merge_line(line, axis="col", towards_start=towards_start)
            score_gained += gained
            moved_any = moved_any or moved
            to_remove.extend(removed)
        self._remove_tiles(to_remove)
        return moved_any, score_gained

    def _slide_columns(self, towards_start: bool) -> Tuple[bool, int]:
        moved_any = False
        score_gained = 0
        to_remove: List[Tile] = []
        for col in range(self.size):
            line = [t for t in self.tiles if t.col == col]
            gained, moved, removed = self._merge_line(line, axis="row", towards_start=towards_start)
            score_gained += gained
            moved_any = moved_any or moved
            to_remove.extend(removed)
        self._remove_tiles(to_remove)
        return moved_any, score_gained

    def _merge_line(
        self, line: List[Tile], axis: str, towards_start: bool
    ) -> Tuple[int, bool, List[Tile]]:
        """Slide and merge a single row's or column's tiles.

        `axis` is the tile attribute ("row" or "col") that changes along
        this line. Tiles are processed in travel order, merged with their
        neighbour when equal (at most once per tile per move), and then
        assigned their final, packed coordinates.
        """
        ordered = sorted(line, key=lambda t: getattr(t, axis), reverse=not towards_start)

        packed: List[Tile] = []
        removed: List[Tile] = []
        score_gained = 0

        i = 0
        while i < len(ordered):
            current = ordered[i]
            nxt = ordered[i + 1] if i + 1 < len(ordered) else None
            if nxt is not None and nxt.value == current.value:
                current.value *= 2
                current.merged = True
                score_gained += current.value
                removed.append(nxt)
                packed.append(current)
                i += 2
            else:
                packed.append(current)
                i += 1

        moved = False
        for index, tile in enumerate(packed):
            new_coord = index if towards_start else (self.size - 1 - index)
            if getattr(tile, axis) != new_coord:
                moved = True
            setattr(tile, axis, new_coord)

        return score_gained, moved, removed

    def _remove_tiles(self, tiles_to_remove: List[Tile]) -> None:
        if not tiles_to_remove:
            return
        remove_ids = {t.id for t in tiles_to_remove}
        self.tiles = [t for t in self.tiles if t.id not in remove_ids]

    # ------------------------------------------------------------------
    def to_grid(self) -> List[List[int]]:
        """Return the board as a plain size x size list of ints (0 = empty)."""
        grid = [[0] * self.size for _ in range(self.size)]
        for tile in self.tiles:
            grid[tile.row][tile.col] = tile.value
        return grid

    def highest_value(self) -> int:
        """Return the value of the largest tile currently on the board."""
        return max((t.value for t in self.tiles), default=0)

    def has_tile_of_value(self, target: int) -> bool:
        """True if any tile has reached at least `target`."""
        return any(t.value >= target for t in self.tiles)

    def is_game_over(self) -> bool:
        """True if there are no empty cells and no adjacent equal tiles remain."""
        grid = self.to_grid()
        for row in grid:
            if 0 in row:
                return False
        for r in range(self.size):
            for c in range(self.size - 1):
                if grid[r][c] == grid[r][c + 1]:
                    return False
        for r in range(self.size - 1):
            for c in range(self.size):
                if grid[r][c] == grid[r + 1][c]:
                    return False
        return True

    # ------------------------------------------------------------------
    def snapshot(self) -> List[Tuple[int, int, int]]:
        """Capture (value, row, col) for every tile - used for undo history."""
        return [(t.value, t.row, t.col) for t in self.tiles]

    def restore(self, snapshot: List[Tuple[int, int, int]]) -> None:
        """Rebuild the board's tiles from a previously captured snapshot."""
        self.tiles = []
        for value, row, col in snapshot:
            tile = Tile(value, row, col)
            tile.just_spawned = False  # no spawn animation when undoing
            self.tiles.append(tile)


# ======================================================================
# Statistics + settings persistence (JSON)
# ======================================================================

@dataclass
class Stats:
    best_score: int = 0
    highest_tile: int = 0
    games_played: int = 0
    games_won: int = 0
    moves_made: int = 0
    total_play_time: float = 0.0
    total_score_sum: int = 0

    @property
    def average_score(self) -> float:
        return (self.total_score_sum / self.games_played) if self.games_played else 0.0


class StatsManager:
    """Loads/saves Stats and settings (like mute) to a JSON file.

    The file is created automatically with sane defaults the first time
    the game runs, and any corruption in the file falls back to defaults
    instead of crashing the game.
    """

    def __init__(self, path: str = DATA_FILE):
        self.path = path
        self.stats = Stats()
        self.muted = False
        self._load()

    def _load(self) -> None:
        """Load stats/settings from disk, creating a fresh file if missing."""
        if not os.path.exists(self.path):
            self._save()
            return
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
            s = data.get("stats", {})
            self.stats = Stats(
                best_score=s.get("best_score", 0),
                highest_tile=s.get("highest_tile", 0),
                games_played=s.get("games_played", 0),
                games_won=s.get("games_won", 0),
                moves_made=s.get("moves_made", 0),
                total_play_time=s.get("total_play_time", 0.0),
                total_score_sum=s.get("total_score_sum", 0),
            )
            self.muted = data.get("settings", {}).get("muted", False)
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            # Corrupt or unreadable file - start fresh rather than crash.
            self.stats = Stats()
            self.muted = False
            self._save()

    def _save(self) -> None:
        """Persist current stats and settings to disk as JSON."""
        data = {
            "stats": {
                "best_score": self.stats.best_score,
                "highest_tile": self.stats.highest_tile,
                "games_played": self.stats.games_played,
                "games_won": self.stats.games_won,
                "moves_made": self.stats.moves_made,
                "total_play_time": round(self.stats.total_play_time, 2),
                "total_score_sum": self.stats.total_score_sum,
                "average_score": round(self.stats.average_score, 2),
            },
            "settings": {
                "muted": self.muted,
            },
        }
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    # ------------------------------------------------------------------
    def record_game_start(self) -> None:
        self.stats.games_played += 1
        self._save()

    def record_move(self) -> None:
        self.stats.moves_made += 1

    def record_game_end(self, final_score: int, won: bool, highest_tile: int) -> None:
        """Commit the results of a finished game to the running statistics."""
        self.stats.total_score_sum += final_score
        self.stats.best_score = max(self.stats.best_score, final_score)
        self.stats.highest_tile = max(self.stats.highest_tile, highest_tile)
        if won:
            self.stats.games_won += 1
        self._save()

    def add_play_time(self, seconds: float) -> None:
        self.stats.total_play_time += seconds

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        self._save()
        return self.muted

    def flush(self) -> None:
        """Force a save - called on quit to make sure nothing is lost."""
        self._save()


# ======================================================================
# Sound
# ======================================================================

class SoundManager:
    """Owns every sound effect (all generated in code) plus the mute toggle."""

    def __init__(self, muted: bool = False):
        self.muted = muted
        self._move_sound = generate_tone(300, 0.06, 0.25)
        self._merge_sound = generate_tone(500, 0.09, 0.30)
        self._win_sound = generate_tone(700, 0.30, 0.35)
        self._gameover_sound = generate_tone(150, 0.35, 0.35)

    def set_muted(self, muted: bool) -> None:
        self.muted = muted

    def _play(self, sound: pygame.mixer.Sound) -> None:
        if not self.muted:
            sound.play()

    def play_move(self) -> None:
        self._play(self._move_sound)

    def play_merge(self) -> None:
        self._play(self._merge_sound)

    def play_win(self) -> None:
        self._play(self._win_sound)

    def play_gameover(self) -> None:
        self._play(self._gameover_sound)


# ======================================================================
# Renderer
# ======================================================================

class Renderer:
    """Everything related to drawing the game to the screen.

    Fonts are cached by size so a Font object is never rebuilt mid-frame.
    Backgrounds are drawn with simple pygame.draw calls rather than
    pre-rendered Surfaces being recreated every frame, keeping per-frame
    allocations limited to the small text/tile surfaces that must change.
    """

    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self._font_cache: Dict[int, pygame.font.Font] = {}

    def get_font(self, size: int) -> pygame.font.Font:
        if size not in self._font_cache:
            self._font_cache[size] = pygame.font.SysFont("arial", size, bold=True)
        return self._font_cache[size]

    @staticmethod
    def font_size_for_value(value: int) -> int:
        digits = len(str(value))
        if digits <= 2:
            return 50
        if digits == 3:
            return 40
        return 30

    # ------------------------------------------------------------------
    def draw_top_bar(self, score: int, best: int, muted: bool, paused: bool) -> None:
        """Draw the title, score/best boxes, and the control hints."""
        pygame.draw.rect(self.screen, BACKGROUND_COLOR, (0, 0, WINDOW_WIDTH, TOP_BAR_HEIGHT))

        title_surface = self.get_font(40).render("2048", True, DARK_TEXT_COLOR)
        self.screen.blit(title_surface, (TILE_GAP, 15))

        self._draw_stat_box("SCORE", score, WINDOW_WIDTH - 200)
        self._draw_stat_box("BEST", best, WINDOW_WIDTH - 100)

        hint_font = self.get_font(16)
        hints = "Arrows/WASD move | U undo | R restart | P pause | M mute | ESC quit"
        self.screen.blit(hint_font.render(hints, True, (150, 140, 130)), (TILE_GAP, 58))

        status_bits = []
        if paused:
            status_bits.append("PAUSED")
        if muted:
            status_bits.append("MUTED")
        if status_bits:
            status_surface = hint_font.render("  ".join(status_bits), True, (180, 60, 60))
            self.screen.blit(status_surface, (TILE_GAP, 82))

    def _draw_stat_box(self, label: str, value: int, x: int) -> None:
        pygame.draw.rect(self.screen, BOARD_BACKGROUND_COLOR, (x, 15, 90, 55), border_radius=6)
        label_surface = self.get_font(18).render(label, True, (238, 228, 218))
        self.screen.blit(label_surface, label_surface.get_rect(center=(x + 45, 30)))
        value_surface = self.get_font(20).render(str(value), True, (255, 255, 255))
        self.screen.blit(value_surface, value_surface.get_rect(center=(x + 45, 52)))

    # ------------------------------------------------------------------
    def draw_board_background(self) -> None:
        """Draw the board frame and the empty-cell placeholders beneath the tiles."""
        pygame.draw.rect(
            self.screen, BOARD_BACKGROUND_COLOR,
            (0, TOP_BAR_HEIGHT, BOARD_PIXELS, BOARD_PIXELS), border_radius=8,
        )
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                x, y = self._cell_pixel_pos(row, col)
                pygame.draw.rect(self.screen, BASE_TILE_COLORS[0], (x, y, TILE_PIXELS, TILE_PIXELS), border_radius=6)

    @staticmethod
    def _cell_pixel_pos(row: float, col: float) -> Tuple[float, float]:
        x = TILE_GAP + col * (TILE_PIXELS + TILE_GAP)
        y = TOP_BAR_HEIGHT + TILE_GAP + row * (TILE_PIXELS + TILE_GAP)
        return x, y

    def draw_tile(self, tile: Tile, now: float) -> None:
        """Draw a single tile, applying slide, spawn, and merge-pop animation."""
        slide_t = ease_out_cubic((now - tile.move_start_time) / SLIDE_DURATION)
        draw_row = lerp(tile.anim_start_row, tile.row, slide_t)
        draw_col = lerp(tile.anim_start_col, tile.col, slide_t)
        x, y = self._cell_pixel_pos(draw_row, draw_col)

        scale = 1.0
        if tile.just_spawned:
            spawn_t = min(max((now - tile.spawn_time) / SPAWN_DURATION, 0.0), 1.0)
            scale = spawn_t
        if tile.merged:
            merge_resolved_at = tile.move_start_time + SLIDE_DURATION
            if now >= merge_resolved_at:
                pop_t = min(max((now - merge_resolved_at) / POP_DURATION, 0.0), 1.0)
                bump = math.sin(pop_t * math.pi) * POP_SCALE_BUMP
                scale = max(scale, 1.0 + bump)

        size = int(TILE_PIXELS * scale)
        if size <= 0:
            return
        offset = (TILE_PIXELS - size) // 2
        rect = (x + offset, y + offset, size, size)

        color = get_tile_color(tile.value)
        pygame.draw.rect(self.screen, color, rect, border_radius=max(2, int(6 * scale)))

        if size > 20:  # skip text on a near-invisible spawning tile
            font = self.get_font(self.font_size_for_value(tile.value))
            text_surface = font.render(str(tile.value), True, get_text_color(tile.value))
            if scale != 1.0:
                w, h = text_surface.get_size()
                text_surface = pygame.transform.smoothscale(
                    text_surface, (max(1, int(w * scale)), max(1, int(h * scale)))
                )
            text_rect = text_surface.get_rect(center=(x + TILE_PIXELS / 2, y + TILE_PIXELS / 2))
            self.screen.blit(text_surface, text_rect)

    def draw_overlay(self, title: str, subtitle: str) -> None:
        """Draw a translucent overlay with a title/subtitle over the board area."""
        overlay = pygame.Surface((BOARD_PIXELS, BOARD_PIXELS), pygame.SRCALPHA)
        overlay.fill((238, 228, 218, 200))
        self.screen.blit(overlay, (0, TOP_BAR_HEIGHT))

        title_surface = self.get_font(50).render(title, True, DARK_TEXT_COLOR)
        self.screen.blit(
            title_surface,
            title_surface.get_rect(center=(WINDOW_WIDTH // 2, TOP_BAR_HEIGHT + BOARD_PIXELS // 2 - 20)),
        )
        subtitle_surface = self.get_font(20).render(subtitle, True, DARK_TEXT_COLOR)
        self.screen.blit(
            subtitle_surface,
            subtitle_surface.get_rect(center=(WINDOW_WIDTH // 2, TOP_BAR_HEIGHT + BOARD_PIXELS // 2 + 25)),
        )

    def render(
        self, board: Board, score: int, best: int, muted: bool, paused: bool,
        overlay: Optional[Tuple[str, str]], now: float,
    ) -> None:
        """Draw a complete frame."""
        self.screen.fill(BACKGROUND_COLOR)
        self.draw_top_bar(score, best, muted, paused)
        self.draw_board_background()
        for tile in board.tiles:
            self.draw_tile(tile, now)
        if overlay is not None:
            self.draw_overlay(*overlay)
        pygame.display.update()


# ======================================================================
# Game - orchestrates everything and owns the main loop
# ======================================================================

class Game:
    """Top-level orchestrator: owns the board, stats, sound, renderer, and input handling."""

    def __init__(self):
        pygame.init()
        pygame.mixer.init()
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption(WINDOW_TITLE)

        self.stats_manager = StatsManager(DATA_FILE)
        self.sound = SoundManager(muted=self.stats_manager.muted)
        self.renderer = Renderer(self.screen)

        self.board = Board(BOARD_SIZE)
        self.score = 0
        self.history: List[Tuple[List[Tuple[int, int, int]], int]] = []

        self.paused = False
        self.game_over = False
        self.has_won = False           # becomes True once 2048 is reached this game
        self.win_overlay_visible = False

        self.game_clock = 0.0          # virtual seconds; frozen while paused/over
        self.session_play_time = 0.0

        self.key_to_direction: Dict[int, Direction] = {
            pygame.K_a: Direction.LEFT, pygame.K_LEFT: Direction.LEFT,
            pygame.K_d: Direction.RIGHT, pygame.K_RIGHT: Direction.RIGHT,
            pygame.K_w: Direction.UP, pygame.K_UP: Direction.UP,
            pygame.K_s: Direction.DOWN, pygame.K_DOWN: Direction.DOWN,
        }
        self.move_dispatch: Dict[Direction, "callable"] = {
            Direction.LEFT: self.board.move_left,
            Direction.RIGHT: self.board.move_right,
            Direction.UP: self.board.move_up,
            Direction.DOWN: self.board.move_down,
        }

        self.start_new_game()

    # ------------------------------------------------------------------
    def start_new_game(self) -> None:
        """Reset all per-game state and record that a new game has begun."""
        self.board.reset()
        self.score = 0
        self.history.clear()
        self.game_over = False
        self.has_won = False
        self.win_overlay_visible = False
        for tile in self.board.tiles:
            tile.spawn_time = self.game_clock
        self.stats_manager.record_game_start()

    # ------------------------------------------------------------------
    def apply_move(self, direction: Direction) -> None:
        """Attempt a move, updating score, history, animation timers, sound, and stats."""
        if self.game_over or self.paused:
            return

        self.history.append((self.board.snapshot(), self.score))
        self.board.clear_transient_flags()
        for tile in self.board.tiles:
            tile.move_start_time = self.game_clock

        moved, score_gained = self.move_dispatch[direction]()

        if not moved:
            self.history.pop()  # nothing changed, don't pollute undo history
            return

        self.score += score_gained
        self.stats_manager.record_move()

        new_tile = self.board.spawn_tile()
        if new_tile is not None:
            new_tile.spawn_time = self.game_clock

        if score_gained > 0:
            self.sound.play_merge()
        else:
            self.sound.play_move()

        if not self.has_won and self.board.has_tile_of_value(2048):
            self.has_won = True
            self.win_overlay_visible = True
            self.sound.play_win()

        if self.board.is_game_over():
            self.end_game()

    def end_game(self) -> None:
        """Mark the current game as finished and persist its results."""
        self.game_over = True
        self.sound.play_gameover()
        self.stats_manager.record_game_end(
            final_score=self.score,
            won=self.has_won,
            highest_tile=self.board.highest_value(),
        )

    def undo(self) -> None:
        """Pop the last saved state off the history stack and restore it (unlimited undo)."""
        if not self.history or self.game_over:
            return
        snapshot, previous_score = self.history.pop()
        self.board.restore(snapshot)
        self.score = previous_score

    def toggle_pause(self) -> None:
        self.paused = not self.paused

    def toggle_mute(self) -> None:
        muted = self.stats_manager.toggle_mute()
        self.sound.set_muted(muted)

    # ------------------------------------------------------------------
    def handle_keydown(self, key: int) -> bool:
        """Handle a single key press. Returns False if the game should quit."""
        if key == pygame.K_ESCAPE:
            return False
        if key == pygame.K_r:
            self.start_new_game()
            return True
        if key == pygame.K_p:
            self.toggle_pause()
            return True
        if key == pygame.K_m:
            self.toggle_mute()
            return True
        if key == pygame.K_u:
            self.undo()
            return True

        if self.win_overlay_visible:
            # Any movement key dismisses the "You Win" banner but still moves.
            self.win_overlay_visible = False

        if key in self.key_to_direction and not self.paused:
            self.apply_move(self.key_to_direction[key])
        return True

    # ------------------------------------------------------------------
    def current_overlay(self) -> Optional[Tuple[str, str]]:
        """Return (title, subtitle) for whichever overlay should currently be shown, if any."""
        if self.game_over:
            return "Game Over!", "Press R to restart"
        if self.win_overlay_visible:
            return "You Win!", "Press any move key to continue, R to restart"
        if self.paused:
            return "Paused", "Press P to resume"
        return None

    # ------------------------------------------------------------------
    def run(self) -> None:
        """The main game loop."""
        clock = pygame.time.Clock()
        running = True

        while running:
            raw_dt = clock.tick(FPS) / 1000.0
            if not self.paused and not self.game_over:
                self.game_clock += raw_dt
                self.session_play_time += raw_dt

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    running = self.handle_keydown(event.key)

            self.renderer.render(
                board=self.board,
                score=self.score,
                best=self.stats_manager.stats.best_score,
                muted=self.stats_manager.muted,
                paused=self.paused,
                overlay=self.current_overlay(),
                now=self.game_clock,
            )

        self._shutdown()

    def _shutdown(self) -> None:
        """Persist final stats before the process exits."""
        self.stats_manager.add_play_time(self.session_play_time)
        self.stats_manager.flush()
        pygame.quit()


def main() -> None:
    """Entry point."""
    Game().run()


if __name__ == "__main__":
    main()
