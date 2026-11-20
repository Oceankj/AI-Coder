"""Every backend module must stay importable.

Stages hand off through shared modules (models.py in particular). If one stage
renames or removes a shared type, another stage's module can break without any
other test noticing. This test imports every module under ai_coder/ to catch it.
"""
import importlib
import pkgutil

import pytest

import ai_coder

MODULES = sorted(
    info.name for info in pkgutil.walk_packages(ai_coder.__path__, prefix="ai_coder.")
)


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)
