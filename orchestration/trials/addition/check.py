"""Deterministic functional acceptance tests for the prepared addition trial.

Only the exact AST of the fixed addition/subtraction fixture is executable.
Anything else is rejected before execution. This is not a general code sandbox.
"""
import argparse
import ast
import json
from pathlib import Path
import sys
import unittest


class AdditionTests(unittest.TestCase):
    add = None

    def test_positive_integers(self):
        self.assertEqual(self.add(2, 3), 5)

    def test_negative_integers(self):
        self.assertEqual(self.add(-2, -3), -5)

    def test_mixed_sign_negative_result(self):
        self.assertEqual(self.add(-7, 3), -4)

    def test_mixed_sign_positive_result(self):
        self.assertEqual(self.add(7, -3), 4)

    def test_zero_left_operand(self):
        self.assertEqual(self.add(0, 5), 5)

    def test_zero_right_operand(self):
        self.assertEqual(self.add(5, 0), 5)

    def test_two_zero_operands(self):
        self.assertEqual(self.add(0, 0), 0)

    def test_large_integer_precision(self):
        result = self.add(10 ** 40, 10 ** 40)
        self.assertEqual(result, 2 * 10 ** 40)
        self.assertIs(type(result), int)

    def test_large_opposite_operands(self):
        self.assertEqual(self.add(-(10 ** 40), 10 ** 40), 0)

    def test_commutative_result(self):
        self.assertEqual(self.add(-3, 2), self.add(2, -3))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check one prepared addition artifact")
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args(argv)
    path = args.artifact / "maths.py"
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > 4096:
        print(json.dumps({"passed": False, "reason": "unsupported fixture file"}))
        return 2
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (ValueError, SyntaxError, UnicodeError):
        print(json.dumps({"passed": False, "reason": "invalid fixture syntax"}))
        return 2
    allowed = {ast.dump(ast.parse("def add(a, b):\n    return a " + operator + " b\n")) for operator in ("+", "-")}
    if ast.dump(tree) not in allowed:
        print(json.dumps({"passed": False, "reason": "candidate exceeds the fixed arithmetic AST"}))
        return 2
    # Execute the already validated tree, never re-read/import a mutable module.
    namespace = {"__builtins__": {}}
    exec(compile(tree, "<validated-addition-fixture>", "exec"), namespace)
    AdditionTests.add = staticmethod(namespace["add"])
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AdditionTests)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    print(json.dumps({"tests": result.testsRun, "failures": len(result.failures),
                      "errors": len(result.errors), "skipped": len(result.skipped),
                      "passed": result.wasSuccessful()}, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
