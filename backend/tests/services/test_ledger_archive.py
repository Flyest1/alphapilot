import hashlib
import json
import stat
import warnings
import zipfile

import pytest

from app.services.ledger import archive


@pytest.fixture
def evidence(tmp_path):
    source = tmp_path / "backups/ledger_statements"
    raw = b"date,private\r\n2026-09-01,account\r\n"
    folder = source / hashlib.sha256(raw).hexdigest()
    folder.mkdir(parents=True)
    (folder / "original.csv").write_bytes(raw)
    mapping = b'{"version":"test"}'
    (folder / f"mapping-{hashlib.sha256(mapping).hexdigest()}.json").write_bytes(mapping)
    return tmp_path, source, tmp_path / "backups/copy.zip"


def test_roundtrip_preserves_exact_bytes(evidence):
    root, source, output = evidence
    receipt = archive.backup(source, output, root=root)
    assert receipt["files"] == 2
    assert archive.verify(output, root=root) == receipt
    destination = root / "backups/restored"
    archive.restore(output, destination, root=root)
    assert {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()} == {
        p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize(
    "mutation", ["hash", "traversal", "secret", "missing", "duplicate", "symlink"]
)
def test_untrusted_archive_rejected_before_destination_created(evidence, mutation):
    root, source, output = evidence
    archive.backup(source, output, root=root)
    with zipfile.ZipFile(output) as stream:
        entries = [(i.filename, stream.read(i)) for i in stream.infolist()]
    if mutation == "hash":
        entries[0] = (entries[0][0], b"corrupt")
    elif mutation == "traversal":
        entries.append(("../escape", b"bad"))
    elif mutation == "secret":
        entries.append((".env", b"secret"))
    elif mutation == "missing":
        entries = [(name, data) for name, data in entries if name != "manifest.json"]
    elif mutation == "duplicate":
        entries.append(entries[0])
    malicious = root / "backups/malicious.zip"
    with zipfile.ZipFile(malicious, "w") as stream:
        for name, data in entries:
            info = zipfile.ZipInfo(name)
            if mutation == "symlink" and name != "manifest.json":
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                stream.writestr(info, data)
    destination = root / "backups/restored"
    with pytest.raises(ValueError):
        archive.restore(malicious, destination, root=root)
    assert not destination.exists()


def test_existing_outputs_and_source_overlap_never_overwritten(evidence):
    root, source, output = evidence
    archive.backup(source, output, root=root)
    before = output.read_bytes()
    with pytest.raises(ValueError):
        archive.backup(source, output, root=root)
    assert output.read_bytes() == before
    with pytest.raises(ValueError):
        archive.backup(source, source / "copy.zip", root=root)
    with pytest.raises(ValueError):
        archive.restore(output, source, root=root)


def test_unknown_source_file_and_empty_archive_rejected(evidence):
    root, source, output = evidence
    (source / ".env").write_text("secret")
    with pytest.raises(ValueError):
        archive.backup(source, output, root=root)
    assert not output.exists()
    empty = root / "backups/empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        archive.backup(empty, output, root=root)


def test_manifest_size_mismatch_rejected(evidence):
    root, source, output = evidence
    archive.backup(source, output, root=root)
    with zipfile.ZipFile(output) as stream:
        entries = {i.filename: stream.read(i) for i in stream.infolist()}
    manifest = json.loads(entries["manifest.json"])
    manifest["files"][0]["size"] += 1
    entries["manifest.json"] = json.dumps(manifest).encode()
    altered = root / "backups/altered.zip"
    with zipfile.ZipFile(altered, "w") as stream:
        for name, data in entries.items():
            stream.writestr(name, data)
    with pytest.raises(ValueError):
        archive.verify(altered, root=root)


@pytest.mark.parametrize(
    "change", ["missing_file", "extra_file", "invalid_version", "duplicate_key"]
)
def test_manifest_must_exactly_describe_all_files(evidence, change):
    root, source, output = evidence
    archive.backup(source, output, root=root)
    with zipfile.ZipFile(output) as stream:
        entries = {i.filename: stream.read(i) for i in stream.infolist()}
    manifest = json.loads(entries["manifest.json"])
    if change == "missing_file":
        del entries[manifest["files"][0]["path"]]
    elif change == "extra_file":
        manifest["files"].pop()
    elif change == "invalid_version":
        manifest["version"] = True
    entries["manifest.json"] = json.dumps(manifest).encode()
    if change == "duplicate_key":
        entries["manifest.json"] = b'{"version":1,"version":1,"files":[]}'
    altered = root / "backups/altered.zip"
    with zipfile.ZipFile(altered, "w") as stream:
        for name, data in entries.items():
            stream.writestr(name, data)
    with pytest.raises(ValueError):
        archive.verify(altered, root=root)


def test_content_addressed_names_and_complete_document_required(evidence):
    root, source, output = evidence
    original = next(source.glob("*/original.csv"))
    original.write_bytes(b"changed")
    with pytest.raises(ValueError):
        archive.backup(source, output, root=root)
    original.unlink()
    with pytest.raises(ValueError):
        archive.backup(source, output, root=root)


def test_oversized_file_rejected_without_publication(evidence, monkeypatch):
    root, source, output = evidence
    archive.backup(source, output, root=root)
    monkeypatch.setattr(archive, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError):
        archive.verify(output, root=root)
    second = root / "backups/second.zip"
    with pytest.raises(ValueError):
        archive.backup(source, second, root=root)
    assert not second.exists()


def test_source_symlink_rejected(evidence):
    root, source, output = evidence
    original = next(source.glob("*/original.csv"))
    external = root / "outside.csv"
    external.write_bytes(original.read_bytes())
    original.unlink()
    try:
        original.symlink_to(external)
    except OSError:
        pytest.skip("Host does not grant symlink creation")
    with pytest.raises(ValueError):
        archive.backup(source, output, root=root)
    assert not output.exists()


def test_paths_outside_backup_root_rejected(evidence):
    root, source, output = evidence
    with pytest.raises(ValueError):
        archive.backup(source, root / "external.zip", root=root)
    archive.backup(source, output, root=root)
    with pytest.raises(ValueError):
        archive.restore(output, root / "outside", root=root)


def test_restore_publish_race_preserves_concurrent_empty_destination(evidence, monkeypatch):
    root, source, output = evidence
    archive.backup(source, output, root=root)
    destination = root / "backups/restored"
    original_mkdir = type(destination).mkdir
    observed = []

    def racing_mkdir(self, *args, **kwargs):
        if self == destination and not observed:
            observed.append(True)
            original_mkdir(self)
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(type(destination), "mkdir", racing_mkdir)
    with pytest.raises(ValueError):
        archive.restore(output, destination, root=root)
    assert observed
    assert destination.is_dir()
    assert list(destination.iterdir()) == []


def test_restore_write_failure_retains_partial_destination(evidence, monkeypatch):
    root, source, output = evidence
    archive.backup(source, output, root=root)
    destination = root / "backups/restored"
    original_open = type(destination).open

    def fail_original_write(self, *args, **kwargs):
        if destination in self.parents and self.name == "original.csv":
            raise OSError("synthetic disk error")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(type(destination), "open", fail_original_write)
    with pytest.raises(OSError):
        archive.restore(output, destination, root=root)
    assert destination.is_dir()
    assert list(destination.glob("*/mapping-*.json"))
    with pytest.raises(ValueError):
        archive.restore(output, destination, root=root)
