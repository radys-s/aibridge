"""Stable application errors exposed by the CLI and future local API."""

from __future__ import annotations


class AIBridgeError(Exception):
    """Base class for expected, user-safe application failures."""

    code = "aibridge_error"


class ConfigurationError(AIBridgeError):
    code = "invalid_configuration"


class DomainValidationError(AIBridgeError):
    code = "invalid_input"


class ProjectNotRegisteredError(AIBridgeError, LookupError):
    code = "project_not_registered"


class MemoryNotFoundError(AIBridgeError, LookupError):
    code = "memory_not_found"


class ContextBudgetError(AIBridgeError):
    code = "context_budget_too_small"


class SecretDetectedError(AIBridgeError):
    code = "secret_detected"


class RepositoryError(AIBridgeError):
    code = "storage_error"


class MigrationError(RepositoryError):
    code = "migration_error"


class UnsupportedEventError(AIBridgeError):
    code = "unsupported_event"


class AgentAdapterError(AIBridgeError):
    code = "agent_adapter_error"
