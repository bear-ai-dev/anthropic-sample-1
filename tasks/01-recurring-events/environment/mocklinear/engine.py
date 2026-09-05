from __future__ import annotations

import threading
import time
from typing import Any

from .faults import FaultInjector
from .journal import Journal
from .registry import ServiceRegistry, build_registries
from .schema_args import coerce_arguments
from .tool_errors import InvalidArguments, NotFound, Throttled, TransientServerError
from .tool_result import ToolResult, result_chars
from .world import World

DEFAULT_LIMIT = 50
PAGE_ARGUMENTS = ("limit", "maxResults", "perPage")


class UnknownService(KeyError):
    pass


class UnknownTool(KeyError):
    pass


class Engine:
    def __init__(
        self,
        scenario: dict[str, Any],
        seed: int,
        journal: Journal,
        registries: dict[str, ServiceRegistry] | None = None,
    ) -> None:
        self.journal = journal
        self.registries = registries or build_registries()
        self.lock = threading.RLock()
        self.world = World(scenario, seed)
        self.injector = FaultInjector(self.world.faults_config, seed)

    def services(self) -> list[str]:
        return list(self.registries)

    def _registry(self, service: str) -> ServiceRegistry:
        registry = self.registries.get(service)
        if registry is None:
            raise UnknownService(service)
        return registry

    def tools(self, service: str) -> list[dict[str, Any]]:
        return self._registry(service).descriptors()

    def reseed(self, scenario: dict[str, Any], seed: int | None) -> None:
        with self.lock:
            resolved = self.world.seed if seed is None else seed
            self.world = World(scenario, resolved)
            self.injector = FaultInjector(self.world.faults_config, resolved)
            self.journal.clear()

    def call(self, service: str, tool: str, arguments: dict[str, Any], via: str) -> ToolResult:
        started = time.perf_counter()
        with self.lock:
            registry = self._registry(service)
            spec = registry.get(tool)
            if spec is None:
                raise UnknownTool(tool)
            world, injector = self.world, self.injector
        entry: dict[str, Any] = {"service": service, "tool": tool, "args": arguments, "via": via}
        try:
            latency = injector.before_call(service, tool)
        except Throttled:
            return self._finish(registry.errors.rate_limited(tool), entry, "throttled", started)
        except TransientServerError:
            return self._finish(registry.errors.server_error(tool), entry, "server_error", started)
        if latency:
            time.sleep(latency)
        try:
            args = coerce_arguments(arguments, spec.input_schema)
            self._cap_page(args, spec.input_schema, service, tool, injector)
            result = spec.handler(world, args)
        except NotFound as error:
            entry["error_kind"] = "not_found"
            return self._finish(
                registry.errors.not_found(tool, error.kind, error.key), entry, "error", started
            )
        except InvalidArguments as error:
            entry["error_kind"] = "invalid_arguments"
            return self._finish(
                registry.errors.invalid_arguments(tool, error.message), entry, "error", started
            )
        return self._finish(result, entry, "ok", started)

    def _cap_page(
        self,
        args: dict[str, Any],
        schema: dict[str, Any],
        service: str,
        tool: str,
        injector: FaultInjector,
    ) -> None:
        properties = schema.get("properties", {})
        for name in PAGE_ARGUMENTS:
            declared = properties.get(name)
            if declared is None:
                continue
            requested = int(args.get(name, declared.get("default", DEFAULT_LIMIT)))
            args[name] = injector.page_size(service, tool, requested)

    def _finish(
        self, result: ToolResult, entry: dict[str, Any], outcome: str, started: float
    ) -> ToolResult:
        entry.setdefault("error_kind", None)
        entry["outcome"] = outcome
        entry["duration_ms"] = int((time.perf_counter() - started) * 1000)
        entry["result_chars"] = result_chars(result)
        entry["page"] = result.page
        self.journal.record(entry)
        return result
