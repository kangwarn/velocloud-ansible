"""Make `ansible_collections.velocloud.api` importable from a repo-root checkout.

The repository root is the collection root, but Ansible's import paths require it
to live at `ansible_collections/<namespace>/<name>/`. Build that layout in a temp
directory with a symlink back to this checkout and put it on sys.path.
"""

import atexit
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GALAXY = yaml.safe_load((ROOT / "galaxy.yml").read_text())

_tree = Path(tempfile.mkdtemp(prefix="collection-src-"))
atexit.register(shutil.rmtree, _tree, ignore_errors=True)
_namespace = _tree / "ansible_collections" / GALAXY["namespace"]
_namespace.mkdir(parents=True)
(_namespace / GALAXY["name"]).symlink_to(ROOT, target_is_directory=True)
sys.path.insert(0, str(_tree))
