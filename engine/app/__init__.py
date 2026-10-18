from pathlib import Path

from dotenv import load_dotenv

# Load engine/.env for local runs (uvicorn, python -m app.verify). Variables already set,
# e.g. by systemd's EnvironmentFile on Vultr or the shell, take precedence.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
