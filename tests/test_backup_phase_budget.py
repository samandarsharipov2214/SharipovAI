"""Exercise the exact embedded production helpers using disposable files."""
from __future__ import annotations

import io
import os
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/vps/export_backup.sh"
GIB = 1024**3
MIB = 1024**2
FLOOR = 20 * GIB + 512 * MIB


def embedded(name):
    source = SCRIPT.read_text().split(f"# BEGIN {name}_PYTHON\n", 1)[1].split(f"# END {name}_PYTHON", 1)[0]
    scope = {"__name__": "backup_test"}
    exec(compile(source, str(SCRIPT), "exec"), scope)
    return scope


def gate(available, extra):
    source = SCRIPT.read_text()
    function = source.split("require_free_space() {", 1)[1].split("\n}\n", 1)[0]
    return subprocess.run(["bash", "-c", f"""
set -Eeuo pipefail
fail() {{ echo "$*" >&2; exit 1; }}
log() {{ :; }}
MIN_FREE_BYTES={20 * GIB}
RESERVE_BYTES={512 * MIB}
MIN_FREE_DISK_GB=20
RESERVE_MIB=512
available_backup_bytes() {{ echo {available}; }}
require_free_space() {{{function}
}}
require_free_space {extra} test
"""], capture_output=True, text=True)


@pytest.mark.parametrize("source", [0, 6_700_000_000, 50_000_000_000, 2**63, 2**80])
def test_preflight_accepts_exact_capacity_and_rejects_shortfall_without_overflow(source):
    assert gate(FLOOR + source, source).returncode == 0
    rejected = gate(FLOOR + source - 1, source)
    assert rejected.returncode != 0
    assert "disk preflight failed" in rejected.stderr


def test_budget_counts_archive_bytes_even_when_disk_usage_is_delayed():
    writer_type = embedded("BOUNDED_ARCHIVE")["BudgetWriter"]
    output = io.BytesIO()
    writer = writer_type(output, ".", FLOOR, lambda _: SimpleNamespace(free=FLOOR + MIB + 8))
    assert writer.write(b"12345678") == 8
    with pytest.raises(RuntimeError, match="budget exhausted"):
        writer.write(b"9")
    assert output.getvalue() == b"12345678"


def test_budget_stops_when_concurrent_work_consumes_disk():
    writer_type = embedded("BOUNDED_ARCHIVE")["BudgetWriter"]
    available = iter([FLOOR + 10 * MIB, FLOOR + 9 * MIB, FLOOR])
    output = io.BytesIO()
    writer = writer_type(output, ".", FLOOR, lambda _: SimpleNamespace(free=next(available)))
    writer.write(b"first")
    with pytest.raises(RuntimeError, match="budget exhausted"):
        writer.write(b"second")
    assert output.getvalue() == b"first"


def test_budget_rejects_floor_without_opening_an_archive():
    writer_type = embedded("BOUNDED_ARCHIVE")["BudgetWriter"]
    with pytest.raises(RuntimeError, match="insufficient"):
        writer_type(io.BytesIO(), ".", FLOOR, lambda _: SimpleNamespace(free=FLOOR))


def test_staging_and_compressed_archive_peak_can_fit_below_two_raw_copies(tmp_path):
    scope = embedded("BOUNDED_ARCHIVE")
    root = tmp_path / "stage"
    (root / "data").mkdir(parents=True)
    source_bytes = 8 * MIB
    (root / "data/large.sqlite3").write_bytes(b"\0" * source_bytes)
    (root / "manifest.json").write_text('{"schema":1}')
    # This disk has room for the staged data, but not a second raw copy.
    assert gate(FLOOR + source_bytes + 3 * MIB, source_bytes).returncode == 0
    assert gate(FLOOR + source_bytes + 3 * MIB, source_bytes * 2).returncode != 0
    output = io.BytesIO()
    writer = scope["BudgetWriter"](output, root, FLOOR, lambda _: SimpleNamespace(free=FLOOR + 3 * MIB))
    with tarfile.open(fileobj=writer, mode="w|gz") as archive:
        archive.add(root / "data", arcname="data")
    assert len(output.getvalue()) < 2 * MIB
    with tarfile.open(fileobj=io.BytesIO(output.getvalue()), mode="r:gz") as archive:
        assert len(archive.extractfile("data/large.sqlite3").read()) == source_bytes


def test_incompressible_archive_exceeding_budget_fails(tmp_path):
    scope = embedded("BOUNDED_ARCHIVE")
    writer = scope["BudgetWriter"](io.BytesIO(), tmp_path, 0, lambda _: SimpleNamespace(free=MIB + 1024))
    with pytest.raises(RuntimeError, match="budget exhausted"):
        with tarfile.open(fileobj=writer, mode="w|gz") as archive:
            content = os.urandom(64 * 1024)
            info = tarfile.TarInfo("random")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def test_retention_protects_active_and_latest_despite_future_mtime(tmp_path):
    retain = embedded("RETENTION")["retain_archives"]
    active = tmp_path / "sharipovai-20260907T100000Z.tar.gz"
    old = tmp_path / "sharipovai-20260906T100000Z.tar.gz"
    future = tmp_path / "sharipovai-20260905T100000Z.tar.gz"
    for path in (active, old, future):
        path.write_bytes(b"archive")
        path.with_name(path.name + ".sha256").write_text("checksum")
    os.utime(future, (2**32, 2**32))
    (tmp_path / "latest.tar.gz").symlink_to(old.name)
    partial = tmp_path / ".sharipovai-20260907.tar.gz.partial-test"
    partial.write_text("active write")
    unknown = tmp_path / "sharipovai-unknown.tar.gz"
    unknown.write_text("preserve")
    retain(tmp_path, active, 2)
    assert active.is_file() and old.is_file() and partial.is_file() and unknown.is_file()
    assert not future.exists()
    assert not future.with_name(future.name + ".sha256").exists()


@pytest.mark.parametrize("name", ["KEEP", "SHARIPOVAI_BACKUP_MIN_FREE_DISK_GB", "SHARIPOVAI_BACKUP_RESERVE_MIB"])
def test_huge_configuration_is_rejected_before_any_directory_mutation(tmp_path, name):
    result = subprocess.run(["bash", str(SCRIPT)], env=os.environ | {name: str(2**64 + 1), "BACKUP_DIR": str(tmp_path / "absent")}, capture_output=True, text=True)
    assert result.returncode != 0
    assert not (tmp_path / "absent").exists()
