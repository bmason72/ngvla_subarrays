#!/usr/bin/env python3
"""Export the upstream Memo-96 pickle tables to portable, inert JSON.

This is a maintainer tool, not a runtime dependency.  It deliberately reads
pickle only from an explicitly supplied trusted source directory, converts all
nested NumPy values to JSON-native values, and verifies the conversion before
writing the result.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


FILES = ("receiver_data.pkl", "subarray_data.pkl")


def _confusion_table(source_dir: Path):
    """Extract the two literal Condon source-count arrays without importing code."""
    path = source_dir / "ngVLA_sensitivity_calculator.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    wanted = {"logSJy", "Ntotsr"}
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in wanted:
            continue
        call = node.value
        if (isinstance(call, ast.Call) and call.args
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "array"):
            found[target.id] = ast.literal_eval(call.args[0])
    if set(found) != wanted:
        raise ValueError("could not find literal confusion arrays in %s" % path)
    return {
        "log_s_jy": _native(found["logSJy"]),
        "n_total_sr": _native(found["Ntotsr"]),
    }, hashlib.sha256(path.read_bytes()).hexdigest()


def _native(value):
    if isinstance(value, dict):
        return {str(key): _native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_native(item) for item in value]
    if isinstance(value, np.ndarray):
        return _native(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError("unsupported value in sensitivity table: %r" % type(value))


def _assert_equal(original, converted, path="root"):
    """Numerically compare the JSON representation with the pickle object."""
    if isinstance(original, dict):
        assert set(map(str, original)) == set(converted), path
        for key, value in original.items():
            _assert_equal(value, converted[str(key)], "%s.%s" % (path, key))
    elif isinstance(original, (list, tuple, np.ndarray)):
        sequence = original.tolist() if isinstance(original, np.ndarray) else original
        assert len(sequence) == len(converted), path
        for index, (left, right) in enumerate(zip(sequence, converted)):
            _assert_equal(left, right, "%s[%d]" % (path, index))
    elif isinstance(original, (float, np.floating)):
        assert float(original) == float(converted), path
    elif isinstance(original, (int, np.integer)):
        assert int(original) == int(converted), path
    else:
        assert original == converted, path


def export(source_dir: Path, output: Path) -> None:
    tables = {}
    checksums = {}
    key_order = {}
    for filename in FILES:
        path = source_dir / filename
        raw = path.read_bytes()
        # These are repository-owned, trusted upstream inputs.  Runtime code
        # never unpickles data.
        original = pickle.loads(raw)
        converted = _native(original)
        _assert_equal(original, converted, filename)
        tables[filename.removesuffix(".pkl")] = converted
        key_order[filename.removesuffix(".pkl")] = list(map(str, original.keys()))
        checksums[filename] = hashlib.sha256(raw).hexdigest()

    confusion, calculator_checksum = _confusion_table(source_dir)
    checksums["ngVLA_sensitivity_calculator.py"] = calculator_checksum

    payload = {
        "schema": "ngvla.memo96.sensitivity-tables",
        "schema_version": 1,
        "provenance": (
            "Exported from ngvla-sensitivity-calculator receiver_data.pkl and "
            "subarray_data.pkl (V. Rosero / ngVLA Memo 96 backing calculator)."
        ),
        "redistribution_note": (
            "Confirm upstream data/code redistribution terms before publishing "
            "this package outside the project collaboration."
        ),
        "source_sha256": checksums,
        "units": {
            "receiver frequency": "GHz",
            "receiver temperatures": "K",
            "subarray baselines": "m",
            "theta_nat_30_GHz": "mas",
        },
        "confusion_counts": confusion,
        "table_key_order": key_order,
        **tables,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    export(args.source_dir, args.output)


if __name__ == "__main__":
    main()
