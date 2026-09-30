"""Composition root for CLI and future API processes."""

from __future__ import annotations

from dataclasses import dataclass

from aibridge.adapters.security import RegexSecretScanner
from aibridge.adapters.sqlite.repository import SQLiteMemoryRepository
from aibridge.application.context import LexicalContextBuilder
from aibridge.application.services import (
    ContextService,
    DoctorService,
    MemoryService,
    ProjectService,
    RunService,
)
from aibridge.config import Settings
from aibridge.memory.curator import MemoryCurator
from aibridge.runs.orchestrator import RunOrchestrator


@dataclass(frozen=True, slots=True)
class Application:
    repository: SQLiteMemoryRepository
    projects: ProjectService
    memories: MemoryService
    contexts: ContextService
    runs: RunService
    doctor: DoctorService


def create_application(settings: Settings | None = None) -> Application:
    resolved_settings = settings or Settings.load()
    repository = SQLiteMemoryRepository(resolved_settings)
    repository.initialize()

    projects = ProjectService(repository)
    context_builder = LexicalContextBuilder(repository)
    scanner = RegexSecretScanner()
    curator = MemoryCurator(repository, scanner)
    orchestrator = RunOrchestrator(repository, context_builder, curator)

    return Application(
        repository=repository,
        projects=projects,
        memories=MemoryService(repository, projects, scanner, curator),
        contexts=ContextService(projects, context_builder),
        runs=RunService(repository, projects, orchestrator),
        doctor=DoctorService(repository),
    )
