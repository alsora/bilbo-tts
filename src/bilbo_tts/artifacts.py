"""Atomic, checksummed storage for pipeline artifacts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeVar

from pydantic import TypeAdapter, ValidationError

from bilbo_tts.models import ContractModel, Identifier, NonEmptyText, Sha256
from bilbo_tts.serialization import canonical_json_bytes, sha256_bytes

ArtifactModel = TypeVar("ArtifactModel", bound=ContractModel)


class ArtifactError(RuntimeError):
    """Base class for persistent artifact failures."""


class ArtifactOwnershipError(ArtifactError):
    """An artifact path escapes the owning workspace."""


class ArtifactCorruptionError(ArtifactError):
    """Stored bytes or payload checksums are invalid."""


class ArtifactCompatibilityError(ArtifactError):
    """Stored data does not satisfy the requested contract."""


class StaleArtifactError(ArtifactError):
    """An upstream dependency has changed or disappeared."""


class ArtifactReference(ContractModel):
    """Stable reference to a stored artifact."""

    path: NonEmptyText
    sha256: Sha256


class ArtifactEnvelope(ContractModel):
    """Checksummed wrapper around a versioned contract payload."""

    schema_version: Literal["artifact-envelope/v1"] = "artifact-envelope/v1"
    artifact_type: Identifier
    payload_sha256: Sha256
    dependencies: tuple[ArtifactReference, ...] = ()
    payload: dict[str, Any]


class BookWorkspace:
    """Own all generated paths for one configured book."""

    def __init__(self, project_root: Path, book_id: str) -> None:
        TypeAdapter(Identifier).validate_python(book_id)
        self.project_root = project_root.expanduser().resolve()
        self.book_id = book_id
        self.root = self.project_root / "work" / book_id
        self.artifacts = ArtifactStore(self.root)


class ArtifactStore:
    """Read and atomically replace artifacts below one workspace root."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def resolve(self, relative_path: str | PurePosixPath) -> Path:
        """Resolve a relative artifact path without permitting escape."""

        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ArtifactOwnershipError(f"artifact path must stay within {self.root}: {relative}")
        candidate = self.root.joinpath(*relative.parts)
        resolved_candidate = candidate.resolve(strict=False)
        if not resolved_candidate.is_relative_to(self.root):
            raise ArtifactOwnershipError(f"artifact path escapes {self.root}: {relative}")
        return candidate

    def write(
        self,
        relative_path: str | PurePosixPath,
        artifact: ContractModel,
        *,
        dependencies: tuple[ArtifactReference, ...] = (),
    ) -> ArtifactReference:
        """Atomically persist an artifact and return its stable reference."""

        target = self.resolve(relative_path)
        self._validate_dependencies(dependencies)
        payload = artifact.model_dump(mode="json")
        envelope = ArtifactEnvelope(
            artifact_type=_artifact_type(artifact),
            payload_sha256=sha256_bytes(canonical_json_bytes(payload)),
            dependencies=dependencies,
            payload=payload,
        )
        data = canonical_json_bytes(envelope) + b"\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_replace(target, data)
        return ArtifactReference(
            path=self._relative_name(target),
            sha256=sha256_bytes(data),
        )

    def read(
        self,
        relative_path: str | PurePosixPath,
        expected_type: type[ArtifactModel],
    ) -> ArtifactModel:
        """Load an artifact after validating bytes, schema, and dependencies."""

        target = self.resolve(relative_path)
        _, envelope = self._load_envelope(target)
        expected_name = _artifact_type(expected_type)
        if envelope.artifact_type != expected_name:
            raise ArtifactCompatibilityError(
                f"artifact {target} contains {envelope.artifact_type}, expected {expected_name}"
            )
        try:
            return expected_type.model_validate(envelope.payload)
        except ValidationError as error:
            raise ArtifactCompatibilityError(
                f"artifact {target} is incompatible with {expected_name}: {error}"
            ) from error

    def reference(self, relative_path: str | PurePosixPath) -> ArtifactReference:
        """Create a reference to the exact stored artifact bytes."""

        target = self.resolve(relative_path)
        data, _ = self._load_envelope(target)
        return ArtifactReference(path=self._relative_name(target), sha256=sha256_bytes(data))

    def _load_envelope(self, target: Path) -> tuple[bytes, ArtifactEnvelope]:
        data = self._read_bytes(target)
        try:
            raw = json.loads(data)
            envelope = ArtifactEnvelope.model_validate(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
            raise ArtifactCorruptionError(
                f"invalid artifact envelope at {target}: {error}"
            ) from error
        actual_payload_sha256 = sha256_bytes(canonical_json_bytes(envelope.payload))
        if actual_payload_sha256 != envelope.payload_sha256:
            raise ArtifactCorruptionError(
                f"payload checksum mismatch for {target}: "
                f"expected {envelope.payload_sha256}, got {actual_payload_sha256}"
            )
        self._validate_dependencies(envelope.dependencies)
        return data, envelope

    def _validate_dependencies(self, dependencies: tuple[ArtifactReference, ...]) -> None:
        paths = [dependency.path for dependency in dependencies]
        if len(paths) != len(set(paths)):
            raise ArtifactCompatibilityError("artifact dependencies must have unique paths")
        for dependency in dependencies:
            target = self.resolve(dependency.path)
            try:
                actual = sha256_bytes(target.read_bytes())
            except FileNotFoundError as error:
                raise StaleArtifactError(
                    f"upstream artifact is missing: {dependency.path}"
                ) from error
            if actual != dependency.sha256:
                raise StaleArtifactError(
                    f"upstream artifact changed: {dependency.path}; "
                    f"expected {dependency.sha256}, got {actual}"
                )

    def _read_bytes(self, target: Path) -> bytes:
        try:
            return target.read_bytes()
        except FileNotFoundError as error:
            raise ArtifactError(f"artifact does not exist: {target}") from error
        except OSError as error:
            raise ArtifactError(f"cannot read artifact {target}: {error}") from error

    def _relative_name(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    @staticmethod
    def _atomic_replace(target: Path, data: bytes) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as error:
            raise ArtifactError(f"cannot atomically write artifact {target}: {error}") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def _artifact_type(value: ContractModel | type[ContractModel]) -> str:
    model_type = value if isinstance(value, type) else type(value)
    return re.sub(r"(?<!^)(?=[A-Z])", "-", model_type.__name__).lower()
