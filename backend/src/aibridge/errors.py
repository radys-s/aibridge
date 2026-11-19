"""Stable application errors exposed by the CLI and future local API."""

from __future__ import annotations

from pydantic import ValidationError


def describe_validation_error(error: ValidationError) -> str:
    """Name each invalid field and the rule it broke, without echoing the input value."""
    problems = []
    for detail in error.errors(include_input=False, include_url=False):
        field = ".".join(str(part) for part in detail["loc"]) or "input"
        problems.append(f"{field}: {detail['msg']}")
    return "; ".join(problems)


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


class CandidateNotFoundError(AIBridgeError, LookupError):
    code = "candidate_not_found"


class CandidateStateError(AIBridgeError):
    code = "candidate_not_pending"


class RunNotFoundError(AIBridgeError, LookupError):
    code = "run_not_found"


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
