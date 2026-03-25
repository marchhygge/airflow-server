"""
Centralised path and config-loading utilities.
All orchestration files import CONTEXTS_DIR and load_config from here.
"""

from pathlib import Path
import yaml
import logging

log = logging.getLogger(__name__)

# Absolute path to the contexts/ directory on the Airflow server.
# Update this value when deploying to a different environment.
CONTEXTS_DIR = "/home/ubuntu/airflow/airflow-server/contexts"


def load_config(config_file_name: str) -> dict:
    """
    Loads a YAML config file from CONTEXTS_DIR.
    args:
     - config_file_name: filename (e.g. 'kmeans_rfm_training.yaml')
    returns:
     - dict: parsed YAML content
    raises:
     - FileNotFoundError: if the config file does not exist
    """
    config_path = Path(CONTEXTS_DIR) / config_file_name
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    log.info(f"Config loaded: {config_path}")
    return config
