"""Bounded local-only ZIP transport for immutable ledger evidence bytes."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_ORIGINAL_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILES = 5000
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
HEX = r"[0-9a-f]{64}"
NAME = re.compile(
    rf"({HEX})/(original\.csv|mapping-({HEX})\.json|"
    rf"context-({HEX})\.json|normalized-{HEX}-{HEX}-({HEX})\.json)"
)


def _fail():
    raise ValueError("Invalid ledger archive")


def _safe_path(path, root):
    base = Path(os.path.abspath(root)) / "backups"
    candidate = Path(os.path.abspath(path))
    try:
        candidate.relative_to(base)
    except ValueError:
        _fail()
    for item in [candidate, *candidate.parents]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            _fail()
    if candidate == base:
        _fail()
    return candidate


def _name(name):
    if not isinstance(name, str):
        _fail()
    match = NAME.fullmatch(name)
    if not match:
        _fail()
    return match


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _validate_files(files):
    if not files or len(files) > MAX_FILES:
        _fail()
    total = 0
    documents = {}
    for name, raw in files.items():
        match = _name(name)
        document, filename, mapping, context, normalized = match.groups()
        limit = MAX_ORIGINAL_BYTES if filename == "original.csv" else MAX_FILE_BYTES
        total += len(raw)
        if len(raw) > limit or total > MAX_TOTAL_BYTES:
            _fail()
        expected = document if filename == "original.csv" else mapping or context or normalized
        if _digest(raw) != expected:
            _fail()
        documents.setdefault(document, set()).add(filename)
    for names in documents.values():
        if "original.csv" not in names or not any(n.startswith("mapping-") for n in names):
            _fail()


def _manifest(files):
    return json.dumps(
        {
            "version": 1,
            "files": [
                {"path": name, "size": len(raw), "sha256": _digest(raw)}
                for name, raw in sorted(files.items())
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _receipt(files):
    return {
        "files": len(files),
        "bytes": sum(map(len, files.values())),
        "manifest_sha256": _digest(_manifest(files)),
    }


def _read_source(source, root):
    if not source.is_dir():
        _fail()
    files = {}
    total = 0
    for directory, dirs, filenames in os.walk(source, followlinks=False):
        for name in dirs:
            path = _safe_path(Path(directory) / name, root)
            if path.parent != source or not re.fullmatch(HEX, name):
                _fail()
        for name in filenames:
            path = _safe_path(Path(directory) / name, root)
            relative = path.relative_to(source).as_posix()
            _name(relative)
            if not stat.S_ISREG(path.lstat().st_mode):
                _fail()
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            total += len(raw)
            if len(raw) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES:
                _fail()
            files[relative] = raw
    _validate_files(files)
    return files


def backup(source, output, *, root):
    """Create an exclusive ZIP containing unencrypted private local evidence."""
    source = _safe_path(source, root)
    output = _safe_path(output, root)
    if output.exists() or output == source or source in output.parents:
        _fail()
    files = _read_source(source, root)
    output.parent.mkdir(parents=True, exist_ok=True)
    _safe_path(output, root)
    descriptor, temporary = tempfile.mkstemp(prefix=".ledger-backup-", dir=output.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, raw in sorted(files.items()):
                    archive.writestr(name, raw)
                archive.writestr("manifest.json", _manifest(files))
            stream.flush()
            os.fsync(stream.fileno())
        _safe_path(output, root)
        try:
            os.link(temporary, output)
        except FileExistsError:
            _fail()
    finally:
        temporary.unlink()
    return _receipt(files)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _read_zip(path, root):
    path = _safe_path(path, root)
    if not path.is_file() or path.stat().st_size > MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES:
        _fail()
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES + 1 or len({i.filename for i in infos}) != len(infos):
                _fail()
            total = 0
            for info in infos:
                if info.filename != "manifest.json":
                    _name(info.filename)
                mode = info.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG) or info.flag_bits & 1:
                    _fail()
                limit = MAX_MANIFEST_BYTES if info.filename == "manifest.json" else MAX_FILE_BYTES
                total += info.file_size
                if info.file_size > limit or total > MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES:
                    _fail()
            if "manifest.json" not in archive.namelist():
                _fail()
            manifest = json.loads(archive.read("manifest.json"), object_pairs_hook=_unique_object)
            if (
                not isinstance(manifest, dict)
                or set(manifest) != {"version", "files"}
                or type(manifest["version"]) is not int
                or manifest["version"] != 1
                or not isinstance(manifest["files"], list)
            ):
                _fail()
            expected = {}
            for item in manifest["files"]:
                if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
                    _fail()
                name = item["path"]
                _name(name)
                if (
                    name in expected
                    or type(item["size"]) is not int
                    or not 0 <= item["size"] <= MAX_FILE_BYTES
                    or not isinstance(item["sha256"], str)
                    or not re.fullmatch(HEX, item["sha256"])
                ):
                    _fail()
                expected[name] = item
            if set(expected) != {i.filename for i in infos} - {"manifest.json"}:
                _fail()
            files = {}
            for name, item in expected.items():
                if archive.getinfo(name).file_size != item["size"]:
                    _fail()
                with archive.open(name) as stream:
                    raw = stream.read(item["size"] + 1)
                if len(raw) != item["size"] or _digest(raw) != item["sha256"]:
                    _fail()
                files[name] = raw
    except (
        OSError,
        KeyError,
        zipfile.BadZipFile,
        RuntimeError,
        UnicodeError,
        json.JSONDecodeError,
    ):
        _fail()
    _validate_files(files)
    return files


def verify(path, *, root):
    """Fully verify every manifest entry and content-addressed evidence filename."""
    return _receipt(_read_zip(path, root))


def restore(path, destination, *, root):
    """Verify and stage, then reserve a new directory and exclusively copy files.

    Publication is not atomic. A failure after reservation preserves the partial
    destination for inspection; retry must use a different new destination.
    """
    destination = _safe_path(destination, root)
    if destination.exists():
        _fail()
    files = _read_zip(path, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _safe_path(destination, root)
    temporary = Path(tempfile.mkdtemp(prefix=".ledger-restore-", dir=destination.parent))
    try:
        for name, raw in files.items():
            target = temporary / name
            target.parent.mkdir(exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
        _safe_path(destination, root)
        try:
            destination.mkdir(exist_ok=False)
        except FileExistsError:
            _fail()
        for name in sorted(files):
            target = _safe_path(destination / name, root)
            target.parent.mkdir(exist_ok=True)
            _safe_path(target, root)
            with (temporary / name).open("rb") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    finally:
        if temporary.exists():
            _safe_path(temporary, root)
            shutil.rmtree(temporary)
    return _receipt(files)
