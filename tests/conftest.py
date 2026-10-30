"""Keep API tests away from application databases and uploaded teacher files."""
import tempfile
from pathlib import Path
from config import config

_test_directory = Path(tempfile.mkdtemp(prefix='evalisense-tests-'))
config.db_path = _test_directory / 'tests.db'
config.storage_dir = _test_directory / 'storage'
config.results_dir = _test_directory / 'results'
