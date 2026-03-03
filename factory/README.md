# Factory Dashboard

Web-based test runner and station management UI for Lager boxes. Run ad-hoc Python scripts or interactive multi-step station tests against hardware connected to your Lager box, all from a browser.

## Prerequisites

- Python 3.12+
- Docker and Docker Compose (for containerized deployment)
- A running Lager box with the `lager` container active

## Quick Start

### Local Development

```bash
cd factory/webapp
pip install -r requirements.txt
FLASK_DEBUG=1 python run.py
```

The dashboard is available at `http://localhost:5001`.

### Docker Deployment

Use the deploy script to deploy to a remote Lager box:

```bash
BOX_USER=myuser ./deploy_factory.sh <BOX_IP>
```

Or run locally with Docker Compose:

```bash
BOX_USER=myuser docker compose up -d --build
```

## Architecture

- **Flask webapp** (`webapp/`) -- serves the dashboard UI on port 5001
- **Box communication** -- HTTP requests to the Lager box service on port 5000 (`/health`, `/cli-version`, `POST /python`)
- **SSH** -- used by `step_runner.py` for interactive station script execution
- **WebSocket** -- real-time communication between the browser and the step runner for interactive steps

### How Scripts Run

1. **Ad-hoc scripts** are uploaded to the box via `POST /python` and streamed back over SSE using the V1 protocol (`<fileno> <length> <content>`)
2. **Station scripts** use the Step protocol -- the script runs over SSH and sends structured JSON events prefixed with `\x02FACTORY:` on stdout. User responses flow back through stdin.

## Writing Test Scripts

### Ad-hoc Scripts

Standard Python scripts with a `main()` function. They run directly on the box:

```python
"""Ad-hoc: My Hardware Check"""
from lager import Net, NetType
import time

def main():
    supply = Net("supply1", type=NetType.Supply)
    supply.enable(voltage=5.0, current_limit=0.5)
    time.sleep(1)
    print(f"Voltage: {supply.voltage()}V")
    supply.disable()

if __name__ == "__main__":
    main()
```

### Station Scripts (Step-based)

Interactive multi-step tests using the `Step` base class:

```python
"""Station: My Validation Test"""
from lager import Net, NetType
from factory import Step, run

class CheckVoltage(Step):
    DisplayName = "Voltage Check"
    Description = "Verify supply outputs 5V"

    def run(self):
        supply = Net("supply1", type=NetType.Supply)
        supply.enable(voltage=5.0, current_limit=0.5)
        v = supply.voltage()
        self.log(f"Measured: {v}V")
        supply.disable()
        return 4.9 <= v <= 5.1

STEPS = [CheckVoltage]

if __name__ == "__main__":
    run(STEPS)
```

## Configuration

### `boxes.json`

Defines the Lager boxes the dashboard connects to. Each entry maps a box ID to its connection details:

```json
{
  "local": {
    "name": "BOXNAME",
    "ip": "host.docker.internal",
    "ssh_user": "your_user",
    "container": "lager"
  }
}
```

- **`name`** -- display name shown in the dashboard
- **`ip`** -- IP address or hostname of the box
- **`ssh_user`** -- SSH username for step runner connections
- **`container`** -- Docker container name running the Lager service

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASK_SECRET_KEY` | `dev-secret-key-change-in-production` | Secret key for Flask sessions. Set in production. |
| `FLASK_DEBUG` | `0` | Set to `1` to enable Flask debug mode |
| `PORT` | `5001` | Port the webapp listens on |
| `HOST` | `0.0.0.0` | Host the webapp binds to |
| `LAGER_WEBAPP_BOXES_FILE` | (none) | Path to `boxes.json` file |
| `LAGER_WEBAPP_DATA_DIR` | `webapp/data` | Directory for persistent script and result storage |
| `BOX_USER` | `lagerdata` | Used by `deploy_factory.sh` and `docker-compose.yml` for SSH paths |

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.
