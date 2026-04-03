# Agent GW Test Suite

Comprehensive test suite for the Agent GW backend application.

## Running The Application

From the repository root, start the full stack with:

```bash
./start_agent_gw.sh
```

The restartable background script `./start_agent_gw.sh` is the recommended start command.

## Test Structure

```
tests/
├── __init__.py           # Test package initialization
├── conftest.py           # Shared fixtures and configuration
├── test_models.py        # Database model tests
├── test_arf_api.py       # ARF HTTP API tests
├── test_acf_server.py    # ACF WebSocket server tests
├── test_moqt_relay.py    # MOQT Relay tests
└── test_integration.py   # Integration tests
```

## Running Tests

### Run all tests
```bash
pytest
```

### Run specific test types

```bash
# Unit tests only
pytest tests/test_models.py tests/test_arf_api.py tests/test_acf_server.py tests/test_moqt_relay.py

# Integration tests only
pytest tests/test_integration.py

# Database model tests
pytest tests/test_models.py

# ARF API tests
pytest tests/test_arf_api.py

# ACF server tests
pytest tests/test_acf_server.py

# MOQT relay tests
pytest tests/test_moqt_relay.py
```

### Run with verbose output
```bash
pytest -v
```

### Run with coverage report
```bash
pytest --cov=. --cov-report=html
```

Coverage report will be generated in `htmlcov/index.html`

## Test Categories

### 1. Unit Tests

#### Database Models (`test_models.py`)
- **TestAgentModel**: Agent CRUD operations, capability handling
- **TestTaskModel**: Task creation and agent relationships
- **TestTrackModel**: Track data storage
- **TestAgentDiscoveryQuery**: Discovery queries with filters

#### ARF API (`test_arf_api.py`)
- **TestAgentCardRegistration**: Agent registration with VC validation
- **TestAgentDiscovery**: Discovery endpoint functionality
- **TestErrorHandling**: Error scenarios and invalid inputs
- **TestACFWebSocketConnection**: ARF to ACF connection

#### ACF Server (`test_acf_server.py`)
- **TestACFSetup**: SETUP message handling
- **TestACFMessageForwarding**: Message routing between agents
- **TestACFConnectionCleanup**: Connection management
- **TestACFWebSocketHandler**: WebSocket protocol handling
- **TestACFMultipleAgents**: Multi-agent scenarios

#### MOQT Relay (`test_moqt_relay.py`)
- **TestMOQTSubscribe**: Subscription handling
- **TestMOQTPublish**: Publishing tracks
- **TestMOQTObjectForwarding**: Object forwarding to subscribers
- **TestMOQTUnsubscribe**: Unsubscription handling
- **TestMOQTClientCleanup**: Client disconnection cleanup
- **TestMOQTMessageProtocol**: Protocol format verification

### 2. Integration Tests (`test_integration.py`)

- **TestAgentRegistrationFlow**: End-to-end agent registration
- **TestDiscoveryAndCollaborationFlow**: Discovery → Collaboration workflow
- **TestErrorScenarios**: Error handling and edge cases
- **TestMultipleAgentsScenario**: Multi-agent interactions
- **TestMOQTWithAgents**: MOQT with agent data streams

## Key Test Scenarios

### Agent Registration
1. Agent sends credentials to ARF `/arf/v1/agent-cards`
2. ARF validates with IDM
3. Agent stored in database
4. Agent connects to ACF via WebSocket
5. Agent status updated to "online"

### Agent Discovery
1. Agent sends discovery request to ARF
2. ARF queries database for matching agents
3. ARF selects best matching agent
4. ARF sends collaboration request via ACF
5. Target agent receives request and responds

### MOQT Data Streaming
1. Agent publishes a track
2. Other agents subscribe to the track
3. Publisher sends objects
4. Objects forwarded to all subscribers
5. Unsubscription cleanup

## Fixtures

Shared fixtures in `conftest.py`:

- `event_loop`: Asyncio event loop for tests
- `reset_database`: Fresh database for each test
- `test_agent_data`: Sample agent data
- `test_vc_data`: Sample VC data
- `test_setup_message`: Sample SETUP message
- `test_collaboration_request`: Sample collaboration request
- `test_collaboration_accept`: Sample collaboration accept
- `test_discover_result`: Sample discovery result
- `mock_websocket`: Mock WebSocket object

## Mocking

Tests use `unittest.mock` for:
- WebSocket connections
- HTTP client calls to IDM
- Database sessions
- Network I/O

## Test Data

Tests use SQLite database (`agent_gw/agent_gw.db`) which is:
- Created fresh for each test
- Populated with test data
- Cleaned up after each test

## Continuous Integration

To run tests in CI/CD:

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests with coverage
pytest --cov=. --cov-report=xml --cov-report=term

# Run specific test file
pytest tests/test_models.py -v
```

## Writing New Tests

### Adding a Unit Test

```python
# tests/test_new_feature.py
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
class TestNewFeature:
    async def test_specific_case(self):
        """Test description"""
        # Setup
        mock_ws = AsyncMock()
        
        # Execute
        result = await some_function(mock_ws)
        
        # Assert
        assert result == expected_value
```

### Adding an Integration Test

```python
# tests/test_integration.py
@pytest.mark.asyncio
class TestNewIntegration:
    async def test_full_workflow(self):
        """Test complete workflow"""
        # Test spans multiple components
        pass
```

## Troubleshooting

### Tests failing with "database locked"
- Database might not be cleaned up properly
- Run tests with `--forked` flag or use fresh test database

### Async tests not running
- Ensure `pytest-asyncio` is installed
- Use `@pytest.mark.asyncio` decorator
- Check `conftest.py` for event_loop fixture

### Import errors
- Ensure you're running from project root
- Check Python path includes project directory

## Coverage Goals

- **Models**: 100% coverage
- **ARF API**: 90%+ coverage
- **ACF Server**: 90%+ coverage
- **MOQT Relay**: 85%+ coverage
- **Integration**: 70%+ coverage

## Contributing

When adding new features:
1. Write tests first (TDD approach)
2. Ensure all tests pass
3. Maintain or improve coverage
4. Update this README with new test scenarios
