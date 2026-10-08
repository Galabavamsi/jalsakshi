"""Fixtures for the store tests: a moto-backed table in ap-south-1."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from jalsakshi.store import Repository, create_table

from .factories import TABLE, Clock

REGION = "ap-south-1"


@pytest.fixture
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake credentials so nothing can reach a real account."""
    for key in ("AWS_PROFILE", "JALSAKSHI_REGION", "JALSAKSHI_TABLE"):
        monkeypatch.delenv(key, raising=False)
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(key, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture
def ddb(aws_env: None) -> Iterator[Any]:
    """A mocked DynamoDB client with the JalSakshi table created."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name=REGION)
        create_table(client, TABLE)
        yield client


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def repo(ddb: Any, clock: Clock) -> Repository:
    return Repository(TABLE, client=ddb, clock=clock)
