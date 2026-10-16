import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# fixed test credentials (set before common.config reads the environment)
os.environ["DEMO_AGENT_SECRET"] = "test-demo"
os.environ["READONLY_WEATHER_SECRET"] = "test-readonly"
os.environ["DOCS_ADMIN_SECRET"] = "test-admin"
