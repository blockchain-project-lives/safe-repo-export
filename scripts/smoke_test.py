"""Install the wheel and verify it outside the source checkout on any OS."""
import argparse
import email
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--dist", default="dist")
args = parser.parse_args()
wheels = list(Path(args.dist).resolve().glob("*.whl"))
if len(wheels) != 1:
    parser.error("expected exactly one wheel in --dist")
with ZipFile(wheels[0]) as archive:
    metadata_path = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
    metadata = email.message_from_bytes(archive.read(metadata_path))
    package_name, version = metadata["Name"], metadata["Version"]
subprocess.run([sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", str(wheels[0])], check=True)
with tempfile.TemporaryDirectory(prefix="export-installed-") as temporary:
    root = Path(temporary)
    subprocess.run([sys.executable, "-I", "-m", "safe_repo_export", "--version"], cwd=root, check=True)
    subprocess.run([sys.executable, "-I", "-m", "safe_repo_export", "init-policies"], cwd=root, check=True)
    policies = root / ".safe-repo-export"
    assert len(list(policies.glob("*.list"))) == 6, "Packaged policies missing"
    repo = root / "project"
    repo.mkdir()
    (repo / "app.py").write_bytes(b'api_key = "example-credential"\n')
    (repo / "settings.toml").write_bytes(b'password = "example-credential"\n')
    def git(*command):
        subprocess.run(["git", "-C", str(repo), *command], check=True, stdout=subprocess.DEVNULL)
    git("init", "-q")
    git("config", "user.name", "Package test")
    git("config", "user.email", "test@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("add", "--all")
    git("commit", "-q", "-m", "fixture")
    output = root / "export"
    subprocess.run([sys.executable, "-I", "-m", "safe_repo_export", "--repo", str(repo),
                    "--output", str(output), "--archive", "zip"], cwd=root, check=True)
    assert "example-credential" not in (output / "app.py").read_text()
    assert "example-credential" not in (output / "settings.toml").read_text()
    assert (root / "export.zip").is_file()
    subprocess.run([sys.executable, "-I", "-c", "from importlib.metadata import distribution; "
                    f"d = distribution({package_name!r}); assert d.version == {version!r}; "
                    "assert not d.requires; print('Installed wheel has no runtime Python dependencies')"], cwd=root, check=True)
print("PASS: installed wheel, bundled policies, committed snapshot export and redaction")
