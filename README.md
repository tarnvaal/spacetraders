# SpaceTraders Automation

A Python-based automation framework for the [SpaceTraders API](https://spacetraders.io) game. This project provides intelligent fleet management, mining operations, market scanning, and automated trading capabilities.

## 🚀 Quick Start

### Prerequisites

- Python 3.10 or higher
- SpaceTraders API token (get one at [spacetraders.io](https://spacetraders.io))

### Installation

1. Clone this repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your environment:
```bash
cp env.example .env
```

4. Edit `.env` and add your SpaceTraders token:
```
AGENT_TOKEN=your_actual_token_here
```

5. (Optional) Configure behavior by copying and editing the config template:
```bash
cp config.ini.template config.ini
```

### Running the Application

```bash
python main.py
```

## ⚙️ Configuration

The application uses `config.ini` for operational settings. If this file doesn't exist, sensible defaults are used.

## 🏗️ Architecture

The codebase is organized into three main layers:

### API Layer (`api/`)

Handles all communication with the SpaceTraders API.

- **`client.py`**: Root API client that orchestrates sub-modules
- **`handle_requests.py`**: HTTP handler with rate limiting and retry logic
  - Rate limits: 2 requests/second, 30 requests/minute
  - Automatic retry on 429 (rate limit) and 5xx errors
  - Intelligent backoff using response headers
- **`agent.py`**: Agent/account information endpoints
- **`fleet.py`**: Ship control operations (navigate, dock, extract, trade)
- **`systems.py`**: Star system discovery and metadata
- **`waypoints.py`**: Waypoint details, markets, and shipyards

### Data Layer (`data/`)

Manages game state and data models.

- **`warehouse.py`**: Central data store for all discovered entities
  - Systems and waypoints cache
  - Fleet state tracking
  - Market price observations
- **`enums.py`**: Game constants (waypoint traits, ship roles, etc.)
- **`models/`**: Data classes for game entities
  - `ship.py`: Ship state and navigation models
  - `system.py`: Star system and waypoint references
  - `waypoints.py`: Detailed waypoint information with traits

### Logic Layer (`logic/`)

Implements high-level game automation and decision-making.

- **`scanner.py`**: Discovery and reconnaissance operations
  - System and waypoint scanning
  - Fleet composition analysis
  - Market price gathering with probe ships
- **`navigation.py`**: Ship movement and trading workflows
  - Waypoint navigation with flight mode control
  - Mining automation (extract until cargo full)
  - Market selection and cargo selling
  - Distance calculations and pathfinding
- **`mine.py`**: Mining ship operations and status display

## 🛠️ Scripts

### Purchase Ship Script

Manually purchase ships at shipyards without modifying main automation logic.

```bash
python -m scripts.purchase_ship --waypoint X1-GZ7-H60 --type SHIP_MINING_DRONE
```

Options:
- `--waypoint`: Shipyard waypoint symbol (default: X1-GZ7-H60)
- `--type`: Ship type to purchase (default: SHIP_MINING_DRONE)
- `--list`: List available ships before purchasing
- `--skip-presence-check`: Skip verification that you have a ship at the waypoint

## 📊 Data Management

### Warehouse Pattern

The `Warehouse` class serves as a central cache for all game data, reducing API calls and improving performance:

- **Systems & Waypoints**: Discovered locations with coordinates and traits
- **Fleet State**: Real-time ship positions, cargo, fuel, and cooldowns
- **Market Intelligence**: Price observations from probe scans
  - Best buy/sell prices for each trade good
  - Market goods acceptance by waypoint

### Market Observations

Market data is recorded with timestamps and can be queried:

```python
# Get best sell price for a good
observation = warehouse.get_best_sell_observation("IRON_ORE")

# Get best purchase price
observation = warehouse.get_best_purchase_observation("FUEL")
```

## 🚢 Ship Roles

The automation recognizes and handles different ship roles:

- **EXCAVATOR**: Mining ships that extract resources
- **SATELLITE**: Probe ships that scan markets and gather intelligence
- **COMMAND/HAULER/etc**: Other ship types (basic support)

## 🔧 Advanced Usage

### Custom Flight Modes

Navigation supports different flight modes for speed/fuel tradeoffs:

- `DRIFT`: Slowest, no fuel cost
- `CRUISE`: Balanced (default)
- `BURN`: Fastest, highest fuel cost
- `STEALTH`: Reduced detection risk

### Distance Calculations

The navigation module uses Euclidean distance (hypot) for waypoint pathfinding within systems. Closest mineable waypoints and markets are automatically selected based on current ship position.

### Cooldown Management

Mining operations automatically respect cooldown timers, polling ship state until extraction is available again.

## 📝 Logging

The application maintains logs in the `logs/` directory:

- **`trades.log`**: Buy/sell transactions with timestamps, prices, and quantities
- **`credits.log`**: Agent credit balance over time

Log format (TSV):
```
timestamp	action	ship	waypoint	symbol	units	unitPrice	totalPrice
```

## 🔍 Error Handling

- **Token Reset Detection**: Automatically exits if API detects token mismatch (error 4113)
- **Rate Limit Handling**: Sleeps until rate limit resets using response headers
- **Retry Logic**: Configurable retries with exponential backoff for transient failures
- **Graceful Degradation**: Missing config values fallback to safe defaults

## 🧪 Development

### Setup Development Environment

Install development dependencies:
```bash
pip install -r requirements-dev.txt
pre-commit install
```

This installs:
- **Black**: Code formatting
- **isort**: Import sorting
- **Ruff**: Fast Python linting
- **mypy**: Static type checking
- **pytest**: Testing framework
- **pre-commit**: Git hooks for automatic checks

### Development Workflow

Use the Makefile for common tasks:

```bash
make install-dev      # Install all dependencies + pre-commit hooks
make format           # Format code with black and isort
make lint             # Run ruff linter
make lint-fix         # Run ruff with auto-fix
make type-check       # Run mypy type checker
make test             # Run tests with pytest
make test-cov         # Run tests with coverage report
make check-all        # Run all checks (format + lint + type-check)
make clean            # Clean build artifacts and caches
```

### Code Quality Tools

#### Black (Code Formatting)
Automatically formats code to a consistent style:
```bash
black .
```

Configuration in `pyproject.toml`:
- Line length: 120 characters
- Target: Python 3.10+

#### isort (Import Sorting)
Sorts and organizes imports:
```bash
isort .
```

Configured to work with Black's style.

#### Ruff (Linting)
Fast, comprehensive linter checking for:
- Code errors and bugs
- Style issues
- Code complexity
- Best practices

```bash
ruff check .           # Check for issues
ruff check --fix .     # Auto-fix issues
```

#### mypy (Type Checking)
Static type checker for type hints:
```bash
mypy .
```

Helps catch type-related bugs before runtime.

#### Pre-commit Hooks
Automatically run checks before each commit:
- Trailing whitespace removal
- End-of-file fixer
- YAML/JSON/TOML validation
- Import sorting (isort)
- Code formatting (black)
- Linting (ruff)
- Type checking (mypy)

Run manually on all files:
```bash
pre-commit run --all-files
```

### Adding New Ship Behaviors

1. Define behavior logic in `logic/navigation.py` or create new logic module
2. Update scheduler in main application loop if using multi-ship coordination
3. Add tests for new behavior in `tests/`
4. Run `make check-all` to ensure code quality
5. Test with single ship before fleet-wide deployment

### Extending API Coverage

1. Add endpoint methods to appropriate API module (`api/fleet.py`, etc.)
2. Update data models in `data/models/` if new entity types
3. Register new entities in `Warehouse` for caching
4. Add type hints to new functions
5. Write tests for new endpoints

## 📚 Dependencies

- **python-dotenv**: Environment variable management
- **requests**: HTTP client
- **requests-ratelimiter**: Rate limiting for API calls
- **pyrate-limiter**: Advanced rate limiting backend
- **urllib3**: HTTP connection pooling

## ⚠️ Important Notes

- The `.env` file containing your API token is excluded from version control
- `config.ini` is also gitignored - use `config.ini.template` as a reference
- Market data can become stale; probe ships periodically rescan for accuracy
- Ships in transit cannot execute commands until arrival

## 🤝 Contributing

When modifying the codebase:

1. Maintain the three-layer architecture (API, Data, Logic)
2. Add module docstrings to new files
3. Use type hints for function parameters and returns
4. Follow PascalCase for class names, snake_case for functions
5. Update this README if adding new features or configuration options

## 📄 License

This project is provided as-is for educational and automation purposes within the SpaceTraders game rules.

## 🔗 Resources

- [SpaceTraders API Documentation](https://docs.spacetraders.io)
- [SpaceTraders Discord Community](https://discord.com/invite/jh6zurdWk5)
- [Game Website](https://spacetraders.io)
