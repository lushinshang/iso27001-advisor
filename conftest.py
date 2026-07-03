"""Shared pytest fixtures for project and eval tests."""

import json
import os

import pytest

from iso27001_advisor.core.search_tool import ISO27001Searcher


@pytest.fixture(scope="session")
def searcher():
    return ISO27001Searcher()


@pytest.fixture(scope="session")
def eval_dataset():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_path = os.path.join(base_dir, "data", "eval_dataset.json")
    with open(dataset_path, "r", encoding="utf-8") as f:
        return json.load(f)
