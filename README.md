# 2048 Pygame

A feature-rich implementation of the classic 2048 puzzle game developed in Python using Pygame. The project follows an object-oriented architecture and focuses on clean code, maintainability, smooth gameplay, and responsive user interaction.

## Features

- Object-oriented architecture
- Official 2048 gameplay mechanics
- Smooth tile movement and merge animations
- Dynamic tile rendering
- Adaptive font scaling
- Unlimited undo functionality
- Pause and restart support
- Persistent high score and game statistics
- Automatic save/load using JSON
- Procedural sound generation (no external audio assets)
- Arrow keys and WASD controls
- Continue playing after reaching the 2048 tile
- Game Over and Victory overlays

---

# Project Structure

```
2048-pygame/
│
├── game2048.py
├── requirements.txt
├── README.md
├── LICENSE
└── .gitignore
```

The project is intentionally kept as a single Python file while maintaining modularity through classes and well-defined methods.

---

# Requirements

- Python 3.10 or later
- Pygame
- NumPy

Install dependencies using

```bash
pip install -r requirements.txt
```

or

```bash
pip install pygame numpy
```

---

# Running the Project

```bash
python game2048.py
```

---

# Controls

| Key | Action |
|------|--------|
| ↑ ↓ ← → | Move tiles |
| W A S D | Alternative movement |
| U | Undo |
| R | Restart |
| P | Pause |
| M | Toggle sound |
| ESC | Exit game |

---

# Gameplay

The objective is to combine tiles with the same value until a tile with the value **2048** is created.

Each move shifts all tiles in the selected direction.

When two adjacent tiles have the same value, they merge into a single tile with twice the value.

After every valid move, a new tile (2 or 4) is randomly generated in an empty position.

The game ends when

- the board contains no empty cells, and
- no adjacent tiles can be merged.

The player may continue playing after reaching the 2048 tile.

---

# Implementation

The project is built using an object-oriented design where each component has a dedicated responsibility.

## Game Management

The main game controller is responsible for

- maintaining the game state
- processing keyboard input
- updating animations
- checking win/loss conditions
- coordinating rendering
- managing statistics and persistence

---

## Board Representation

The board is represented as a 4×4 grid.

Each position stores the current tile state and is updated after every valid move.

This structure allows efficient movement, collision detection, merging, and rendering.

---

## Tile Movement Algorithm

The movement system is implemented explicitly for all four directions instead of relying on matrix rotation.

Each movement follows the same sequence:

1. Compress all tiles toward the selected direction.
2. Merge adjacent tiles with equal values.
3. Compress again to remove gaps created by merging.
4. Spawn a new tile if the board changed.

Example

Before

```
2 0 2 4
```

Compress

```
2 2 4 0
```

Merge

```
4 0 4 0
```

Compress

```
4 4 0 0
```

This implementation follows the official 2048 game mechanics.

---

# Merge Logic

Only one merge is allowed per tile during a single move.

Example

```
2 2 2 2
```

becomes

```
4 4 0 0
```

instead of

```
8 0 0 0
```

which matches the original game's behavior.

---

# Animation System

Tile movement uses interpolation between previous and current positions.

The animation system calculates intermediate positions based on elapsed time, producing smooth transitions regardless of frame rate.

Additional animations include

- tile spawn scaling
- merge pop effect
- overlay transitions

---

# Rendering

Rendering is separated from gameplay logic.

The renderer is responsible for

- drawing the board
- rendering tiles
- adaptive font scaling
- score display
- overlays
- animation frames

Fonts are cached to avoid unnecessary recreation during rendering.

---

# Scoring System

Whenever two tiles merge,

```
X + X = 2X
```

the resulting value is added to the current score.

Example

```
64 + 64 = 128
```

adds

```
128
```

to the player's score.

The highest score is stored persistently.

---

# Undo System

The project supports unlimited undo operations.

Before every successful move, the complete game state is stored in a history stack.

Undo restores

- board state
- score
- animation state

without affecting saved statistics.

---

# Persistent Storage

Game statistics are stored automatically using JSON.

Stored information includes

- best score
- games played
- games won
- highest tile achieved
- move count
- total play time
- average score
- user settings

The file is automatically created if it does not exist.

---

# Audio

The project generates sound effects procedurally using NumPy.

No external audio files are required.

Generated sounds include

- tile movement
- tile merging
- victory
- game over

---

# Object-Oriented Design

The application is organized into logical components that separate gameplay from rendering and persistence.

This design improves

- readability
- maintainability
- extensibility
- debugging

Future features such as AI players, themes, larger boards, or online leaderboards can be added with minimal changes to the existing architecture.

---

# Performance Considerations

The implementation includes several optimizations:

- cached fonts
- delta-time animations
- efficient rendering loop
- minimal object allocation during gameplay
- lightweight save system

---

# Future Improvements

Possible extensions include

- multiple board sizes
- AI solver (Expectimax)
- custom themes
- achievements
- replay system
- online leaderboard
- touch controls
- configurable key bindings

---

# License

This project is licensed under the MIT License.
