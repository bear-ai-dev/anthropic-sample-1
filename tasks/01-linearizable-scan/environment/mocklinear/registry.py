from __future__ import annotations

from typing import Any, Protocol

from .linear import errors as linear_errors
from .linear import register as linear_register
from .scenario import SERVICE
from .tool_result import ToolResult
from .tool_spec import ToolSpec


class VendorErrors(Protocol):
    def rate_limited(self, tool: str) -> ToolResult: ...

    def server_error(self, tool: str) -> ToolResult: ...

    def invalid_arguments(self, tool: str, message: str) -> ToolResult: ...

    def not_found(self, tool: str, kind: str, key: str) -> ToolResult: ...


class ServiceRegistry:
    def __init__(self, service: str, specs: list[ToolSpec], errors: VendorErrors) -> None:
        self.service = service
        self.errors = errors
        self._specs = {spec.name: spec for spec in specs}

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def descriptors(self) -> list[dict[str, Any]]:
        return [self._specs[name].descriptor() for name in sorted(self._specs)]


def build_registries() -> dict[str, ServiceRegistry]:
    return {SERVICE: ServiceRegistry(SERVICE, linear_register.specs(), linear_errors.ERRORS)}
