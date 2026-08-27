"""Immutable registries used by foreground workers."""

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from co_scientist.ports.external_provider import ExternalProvider
from co_scientist.skills.loader import load_skill


class SkillRegistry:
    """Resolve a skill directory by its exact immutable identity."""

    def __init__(self, skills: Mapping[tuple[str, str], Path]) -> None:
        resolved: dict[tuple[str, str], Path] = {}
        for identity, directory in skills.items():
            manifest = load_skill(directory)
            if identity != (manifest.id, manifest.version):
                raise ValueError("skill registry identity does not match manifest")
            resolved[identity] = directory
        self._skills = MappingProxyType(resolved)

    def resolve(self, skill_id: str, skill_version: str) -> Path:
        try:
            return self._skills[(skill_id, skill_version)]
        except KeyError as error:
            raise KeyError(f"unknown skill identity: {skill_id}@{skill_version}") from error


class ProviderRegistry:
    """Resolve providers by immutable configuration identity."""

    def __init__(self, providers: Mapping[str, ExternalProvider]) -> None:
        if any(not provider_id for provider_id in providers):
            raise ValueError("provider identities must be non-empty")
        self._providers = MappingProxyType(dict(providers))

    def resolve(self, provider_id: str) -> ExternalProvider:
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise KeyError(f"unknown provider identity: {provider_id}") from error
