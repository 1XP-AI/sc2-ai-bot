# SC2 AI Bot 🎮

StarCraft II AI Bot using [BurnySc2](https://github.com/BurnySc2/python-sc2) (python-sc2 fork).

## Requirements

- **StarCraft II** (Free Starter Edition works)
- **Python 3.10+** (macOS default is 3.9 — need to install via Homebrew)
- **Maps** (basic maps included, ladder maps optional)

## Setup

### macOS

```bash
# Install Python 3.12 via Homebrew
brew install python@3.12

# Verify
python3.12 --version

# Install dependencies
python3.12 -m pip install -r requirements.txt

# Set SC2 path (default for macOS)
export SC2PATH="/Applications/StarCraft II"
```

### Linux

```bash
# Install Python 3.12
sudo apt install python3.12 python3.12-pip

# Install dependencies
python3.12 -m pip install -r requirements.txt

# Set SC2 path
export SC2PATH="$HOME/StarCraftII"
```

### Download Ladder Maps (Optional)

Basic maps (Simple64, Simple128, etc.) are included with SC2. For ladder maps (4-player maps, ranked maps):

```bash
cd "/Applications/StarCraft II/Maps"    # macOS
# cd "$HOME/StarCraftII/Maps"           # Linux

curl -LO https://github.com/BurnySc2/python-sc2/releases/download/maps/maps.zip
unzip maps.zip
rm maps.zip
```

Or use the included script:
```bash
python3.12 download_maps.py
```

## Run

```bash
# Bot vs Computer (Medium difficulty, fast mode)
python3.12 bot.py

# Real-time speed (watch the game play out normally)
python3.12 bot.py --realtime

# Change difficulty: easy, medium, hard, harder, veryhard, elite
python3.12 bot.py --difficulty hard

# Change enemy race
python3.12 bot.py --race zerg

# Change map
python3.12 bot.py --map Simple128

# Save replay after game
python3.12 bot.py --save-replay
```

## Bot Strategies

### `bot.py` - Protoss 2-Gate Timing Rush
- Build 3 Gateways with Cybernetics Core
- Chrono Boost production
- Mass Zealots early → Stalker transition
- All-in attack at 15+ army supply

### `zerg_bot.py` - Zerg Macro
- Hatchery-first expand (up to 3 bases)
- Queen inject larvae
- Zergling → Roach composition
- Attack at 25+ army supply

### `terran_bot.py` - Terran Bio
- 3 Barracks with Tech Labs
- Orbital Command + MULE
- Marine/Marauder + Medivac
- Stim timing push at 20+ army

## Multiplayer

### Bot vs You (play against your own bot!)

```python
from sc2.player import Bot, Human

run_game(
    maps.get("Simple64"),
    [
        Bot(Race.Protoss, ProtossBot()),
        Human(Race.Terran),  # You play!
    ],
    realtime=True,  # Must be True for human players
)
```

### Bot vs Bot (local)

```python
run_game(
    maps.get("Simple64"),
    [
        Bot(Race.Protoss, ProtossBot()),
        Bot(Race.Zerg, ZergBot()),
    ],
    realtime=False,
)
```

### Free-For-All (up to 4 players)

Requires a 4-player map (download ladder maps first):

```python
run_game(
    maps.get("Acropolis LE"),
    [
        Bot(Race.Protoss, ProtossBot()),
        Computer(Race.Zerg, Difficulty.Medium),
        Computer(Race.Terran, Difficulty.Hard),
        Computer(Race.Protoss, Difficulty.VeryHard),
    ],
    realtime=False,
)
```

### 2v2

```python
run_game(
    maps.get("Acropolis LE"),
    [
        Bot(Race.Protoss, ProtossBot()),    # Your team
        Computer(Race.Zerg, Difficulty.Medium),  # Your ally
        Computer(Race.Terran, Difficulty.Hard),  # Enemy 1
        Computer(Race.Protoss, Difficulty.Hard), # Enemy 2
    ],
    realtime=False,
)
```

### AI Arena (Online Ladder)

Upload your bot to [AI Arena](https://aiarena.net) to compete against bots from around the world with ELO rankings.

```bash
pip install aiarena-client
```

## Troubleshooting

### macOS: Python version too old
```
# macOS ships with Python 3.9 — burnysc2 requires 3.10+
brew install python@3.12
python3.12 -m pip install -r requirements.txt
```

### macOS: SC2 crashes when launched via SSH/Termius
SC2 must be launched from **Terminal.app directly**, not through SSH clients (Termius, iTerm via SSH, etc.). macOS security (TCC) blocks permissions when the "responsible process" is an SSH client.

### Map not found
```bash
# Check available maps
ls "/Applications/StarCraft II/Maps/"

# Download ladder maps
cd "/Applications/StarCraft II/Maps"
curl -LO https://github.com/BurnySc2/python-sc2/releases/download/maps/maps.zip
unzip maps.zip && rm maps.zip
```

### Game runs too fast
Add `--realtime` flag, or set `realtime=True` in code.

### Rosetta errors on Apple Silicon
```bash
# If you see "database disk image is malformed" errors
sudo rm -rf /var/db/oah
# Then reboot
```

## Project Structure

```
├── bot.py              # Protoss bot (main)
├── zerg_bot.py         # Zerg bot
├── terran_bot.py       # Terran bot
├── download_maps.py    # Map downloader
├── requirements.txt    # Dependencies
└── README.md
```

## TODO

- [ ] Scouting (Probe / Observer)
- [ ] Multi-base expansion
- [ ] Focus fire micro
- [ ] Defensive reactions (detect enemy rush)
- [ ] LLM integration (Claude/GPT for strategic decisions)

```python
# Future concept: LLM-powered strategy
game_state = observe_game()
strategy = claude.decide(game_state)  # "expand" / "attack" / "defend"
execute(strategy)
```
