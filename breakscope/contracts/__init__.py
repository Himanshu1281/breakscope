from pathlib import Path

from breakscope.changes import APIChange
from breakscope.contracts.diff import diff_contracts
from breakscope.contracts.loader import load_spec
from breakscope.contracts.model import Contract
from breakscope.contracts.normalize import normalize


def load_contract(path: Path) -> Contract:
    return normalize(load_spec(path))


def diff_files(old: Path, new: Path) -> tuple[list[APIChange], Contract, Contract]:
    a, b = load_contract(old), load_contract(new)
    return diff_contracts(a, b), a, b


__all__ = ["Contract", "diff_contracts", "diff_files", "load_contract"]
