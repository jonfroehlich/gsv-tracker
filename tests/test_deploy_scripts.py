"""Guard tests for deploy_makelab1.sh.

The website deploy runs ``rsync --delete`` against the public docroot, which
sits right next to the ~15 GB (irreplaceable) ``data/`` directory. A wrong
filter could wipe it. These tests shell out to the REAL script in --dry-run mode
(so they can never drift from the actual filter list) and assert that data/ is
protected, legacy repo junk is swept, and dev tooling stays off the web server.

Skipped automatically where bash/rsync aren't available.
"""

import os
import shutil
import subprocess

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_PROJECT_ROOT, "deploy_makelab1.sh")

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("rsync") is None,
    reason="deploy script test needs bash + rsync",
)


def test_deploy_dryrun_protects_data_sweeps_junk_excludes_devtooling(tmp_path):
    docroot = tmp_path / "docroot"
    # Protected content (must survive --delete):
    (docroot / "data").mkdir(parents=True)
    (docroot / "data" / "seattle.csv.gz").write_text("PRECIOUS 15GB")
    (docroot / "poster").mkdir()
    (docroot / "poster" / "p.png").write_text("x")
    # Legacy full-repo junk that a flatten should sweep:
    (docroot / "scripts").mkdir()
    (docroot / "scripts" / "old.py").write_text("junk")
    (docroot / "CLAUDE.md").write_text("junk")
    (docroot / "www").mkdir()  # legacy pre-flatten subdir
    (docroot / "www" / "stale.html").write_text("old")

    env = {**os.environ, "GSV_DOCROOT": str(docroot)}
    # --dry-run skips git pull and applies nothing; runs against the repo's real www/.
    r = subprocess.run(
        ["bash", _SCRIPT, "--dry-run"],
        cwd=_PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"stderr:\n{r.stderr}"
    out = r.stdout

    # data/ and poster/ are protected — never touched, never mentioned.
    assert "seattle.csv.gz" not in out
    assert "p.png" not in out

    # Legacy repo junk is swept by --delete.
    assert "scripts/old.py" in out
    assert "CLAUDE.md" in out
    assert "stale.html" in out  # the old docroot/www/ subdir

    # Dev tooling never reaches the web server.
    assert "node_modules" not in out

    # The site is flattened to the docroot root.
    assert "index.html" in out
    assert "city.html" in out
