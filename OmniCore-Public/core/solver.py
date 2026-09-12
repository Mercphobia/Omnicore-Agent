"""Z3 theorem prover integration for constraint solving and optimisation.

DNA: Oracle (symbolic reasoning, SMT solving).

Provides a Solver class wrapping Microsoft's Z3 theorem prover with
a graceful fallback when z3-solver is not installed.  Supports:

    - solve_constraints: find variable assignments satisfying constraints
    - optimize: minimise/maximise an objective under constraints
    - check_sat: check satisfiability of an expression
    - to_smt2: export constraints to SMT-LIB2 format

Usage::

    s = Solver()
    result = s.solve_constraints(
        variables={"x": "Int", "y": "Int"},
        constraints=["x > 0", "y > x", "x + y < 10"],
    )
    print(result)  # {"status": "sat", "assignment": {"x": 1, "y": 2}}
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Any, Optional

# ── Optional Z3 import ────────────────────────────────────────────────

_z3_available = False
_z3_module: Any = None

try:
    import z3 as _z3_module
    _z3_available = True
except ImportError:
    pass


# ── Result types ──────────────────────────────────────────────────────

@dataclass
class SolveResult:
    """Result of a constraint-solving operation."""
    status: str                      # "sat", "unsat", "unknown", "z3_unavailable"
    assignment: dict[str, Any] = field(default_factory=dict)
    model: Optional[Any] = None      # Raw Z3 model (only when z3 is available)
    smt2: str = ""                   # SMT-LIB2 representation of the problem


@dataclass
class OptimizeResult:
    """Result of an optimisation operation."""
    status: str                      # "sat", "unsat", "unknown", "z3_unavailable"
    assignment: dict[str, Any] = field(default_factory=dict)
    objective_value: Optional[float] = None
    smt2: str = ""


# ── Solver ────────────────────────────────────────────────────────────

class Solver:
    """Z3 theorem prover wrapper with graceful fallback.

    All methods return results with ``status="z3_unavailable"`` when the
    ``z3-solver`` package is not installed.

    Supported variable types: ``"Int"``, ``"Real"``, ``"Bool"``, ``"BitVec"``.

    Constraints are Python expression strings (e.g. ``"x > 0"``) that are
    parsed with Z3's ``eval`` or built from symbolic variables.
    """

    _Z3_ERROR = "z3_unavailable"

    def __init__(self):
        """Initialise.  Z3 availability is auto-detected."""
        self._has_z3 = _z3_available
        self._z3 = _z3_module

    # ── Public API ────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """Whether Z3 is installed and available."""
        return self._has_z3

    def solve_constraints(
        self,
        variables: dict[str, str],
        constraints: list[str],
    ) -> SolveResult:
        """Find a variable assignment satisfying all constraints.

        Args:
            variables: Map of variable name → type (``"Int"``, ``"Real"``, ``"Bool"``, ``"BitVec"``).
            constraints: List of constraint strings, e.g. ``["x > 0", "x + y == 10"]``.

        Returns:
            SolveResult with status and assignment (if ``sat``).

        Example::

            >>> s = Solver()
            >>> s.solve_constraints({"x": "Int", "y": "Int"}, ["x > 0", "y > x", "x + y < 10"])
            SolveResult(status='sat', assignment={'x': 1, 'y': 2}, ...)
        """
        if not self._has_z3:
            return SolveResult(
                status=self._Z3_ERROR,
                smt2=self._to_smt2_fallback(variables, constraints),
            )

        sym_vars = self._make_variables(variables)
        smt2 = self._to_smt2(variables, constraints)

        solver = self._z3.Solver()
        for c_str in constraints:
            try:
                solver.add(eval(c_str, {"__builtins__": {}}, {**sym_vars, "z3": self._z3}))
            except Exception:
                # Fallback: try with z3 module globals
                solver.add(
                    eval(c_str, {"__builtins__": {}, **self._z3.__dict__}, sym_vars)
                )

        status_str = str(solver.check())
        assignment: dict[str, Any] = {}

        if status_str == "sat":
            model = solver.model()
            for name, var in sym_vars.items():
                val = model.evaluate(var)
                assignment[name] = self._z3_value_to_python(val)

            return SolveResult(
                status="sat",
                assignment=assignment,
                model=model,
                smt2=smt2,
            )

        return SolveResult(status=status_str, smt2=smt2)

    def optimize(
        self,
        objective: str,
        constraints: list[str],
        variables: dict[str, str] | None = None,
        maximize: bool = True,
    ) -> OptimizeResult:
        """Minimise or maximise an objective function under constraints.

        Auto-detects variable names from the constraint/objective strings
        if *variables* is not provided.

        Args:
            objective: Expression to optimise, e.g. ``"x + y"``.
            constraints: List of constraint strings.
            variables: Optional variable name → type map.  Auto-detected if omitted.
            maximize: ``True`` to maximise, ``False`` to minimise.

        Returns:
            OptimizeResult with status, assignment, and objective_value.

        Example::

            >>> s = Solver()
            >>> s.optimize("x + y", ["x >= 0", "y >= 0", "x + y <= 20"], maximize=True)
            OptimizeResult(status='sat', assignment={'x': 20, 'y': 0}, objective_value=20.0)
        """
        if not self._has_z3:
            all_cs = constraints + [objective]
            smt2 = self._to_smt2_fallback(
                variables or self._infer_variables(all_cs), all_cs
            )
            return OptimizeResult(status=self._Z3_ERROR, smt2=smt2)

        if variables is None:
            variables = self._infer_variables(constraints + [objective])

        sym_vars = self._make_variables(variables)
        smt2 = self._to_smt2(variables, constraints + [f"optimize: {objective}"])

        opt = self._z3.Optimize()
        for c_str in constraints:
            opt.add(eval(c_str, {"__builtins__": {}}, sym_vars))

        obj_expr = eval(objective, {"__builtins__": {}}, sym_vars)

        if maximize:
            opt.maximize(obj_expr)
        else:
            opt.minimize(obj_expr)

        status_str = str(opt.check())
        assignment: dict[str, Any] = {}
        obj_val: Optional[float] = None

        if status_str == "sat":
            model = opt.model()
            for name, var in sym_vars.items():
                val = model.evaluate(var)
                assignment[name] = self._z3_value_to_python(val)
            obj_val_raw = model.evaluate(obj_expr)
            obj_val = self._z3_value_to_python(obj_val_raw)
            if obj_val is not None:
                obj_val = float(obj_val)

        return OptimizeResult(
            status=status_str,
            assignment=assignment,
            objective_value=obj_val,
            smt2=smt2,
        )

    def check_sat(self, expression: str, variables: dict[str, str] | None = None) -> str:
        """Check whether a single expression is satisfiable.

        Args:
            expression: A Z3 expression string, e.g. ``"And(x > 0, x < 5)"``.
            variables: Variable name → type map.  Auto-detected if omitted.

        Returns:
            One of ``"sat"``, ``"unsat"``, ``"unknown"``, or ``"z3_unavailable"``.
        """
        if not self._has_z3:
            return self._Z3_ERROR

        if variables is None:
            variables = self._infer_variables([expression])

        sym_vars = self._make_variables(variables)

        try:
            expr = eval(expression, {"__builtins__": {}}, sym_vars)
        except Exception:
            expr = eval(
                expression,
                {"__builtins__": {}, **self._z3.__dict__},
                sym_vars,
            )

        solver = self._z3.Solver()
        solver.add(expr)
        return str(solver.check())

    def to_smt2(
        self,
        variables: dict[str, str],
        constraints: list[str],
    ) -> str:
        """Export constraints to SMT-LIB2 format.

        This is always available — it does not require Z3 to be installed.
        """
        return self._to_smt2_fallback(variables, constraints)

    # ── Internals ─────────────────────────────────────────────────────

    def _make_variables(self, variables: dict[str, str]) -> dict[str, Any]:
        """Create Z3 symbolic variables from a name→type map."""
        if not self._has_z3:
            return {}

        type_map = {
            "Int": self._z3.Int,
            "Real": self._z3.Real,
            "Bool": self._z3.Bool,
            "BitVec": lambda name: self._z3.BitVec(name, 32),
        }

        sym_vars: dict[str, Any] = {}
        for name, vtype in variables.items():
            factory = type_map.get(vtype)
            if factory is None:
                raise ValueError(
                    f"Unknown variable type '{vtype}'. "
                    f"Use one of: {list(type_map.keys())}"
                )
            sym_vars[name] = factory(name)

        # Also register common Z3 functions so expressions can use them
        sym_vars["And"] = self._z3.And
        sym_vars["Or"] = self._z3.Or
        sym_vars["Not"] = self._z3.Not
        sym_vars["Implies"] = self._z3.Implies
        sym_vars["If"] = self._z3.If
        sym_vars["Sum"] = self._z3.Sum
        sym_vars["Product"] = self._z3.Product
        sym_vars["Distinct"] = self._z3.Distinct

        return sym_vars

    @staticmethod
    def _infer_variables(expressions: list[str]) -> dict[str, str]:
        """Infer variable types from expressions by scanning for identifiers.

        Simple heuristic: any lowercase identifier not in a known set is
        treated as an ``Int`` variable.
        """
        import re

        known = {
            "And", "Or", "Not", "Implies", "If", "Sum", "Product", "Distinct",
            "Int", "Real", "Bool", "BitVec", "True", "False", "None",
            "min", "max", "abs", "len", "range", "int", "float", "bool",
            "print", "isinstance", "type",
        }

        identifiers: set[str] = set()
        for expr in expressions:
            ids = re.findall(r'\b([a-zA-Z_]\w*)\b', expr)
            for i in ids:
                if i[0].islower() and i not in known:
                    identifiers.add(i)

        return {name: "Int" for name in identifiers}

    @staticmethod
    def _z3_value_to_python(val: Any) -> Any:
        """Convert a Z3 AST value to a plain Python value."""
        if val is None:
            return None
        try:
            if hasattr(val, "as_long"):
                return val.as_long()
            if hasattr(val, "as_fraction"):
                frac = val.as_fraction()
                return float(frac.numerator) / float(frac.denominator)
            if hasattr(val, "numerator_as_long"):
                return val.numerator_as_long() / float(val.denominator_as_long())
        except Exception:
            pass
        # Bool
        try:
            if hasattr(val, "__bool__"):
                return bool(val)
        except Exception:
            pass
        return str(val)

    def _to_smt2(self, variables: dict[str, str], constraints: list[str]) -> str:
        """Generate SMT-LIB2 using Z3's built-in converter (requires Z3)."""
        if not self._has_z3:
            return self._to_smt2_fallback(variables, constraints)

        sym_vars = self._make_variables(variables)
        solver = self._z3.Solver()
        for c in constraints:
            try:
                solver.add(eval(c, {"__builtins__": {}}, sym_vars))
            except Exception:
                solver.add(eval(c, {"__builtins__": {}, **self._z3.__dict__}, sym_vars))
        return solver.to_smt2()

    @staticmethod
    def _to_smt2_fallback(variables: dict[str, str], constraints: list[str]) -> str:
        """Generate SMT-LIB2 manually (no Z3 required)."""
        lines = ["; SMT-LIB2 generated by OmniCore Solver (no Z3)"]
        logic = "QF_LIA"  # default to linear integer arithmetic

        # Determine logic from variable types
        types = set(variables.values())
        if "Real" in types:
            logic = "QF_LRA"
        if "Bool" in types and len(types) == 1:
            logic = "QF_BOOL"
        if "BitVec" in types:
            logic = "QF_BV"

        lines.append(f"(set-logic {logic})")

        for name, vtype in variables.items():
            lines.append(f"(declare-fun {name} () {vtype})")

        for c in constraints:
            lines.append(f"(assert {Solver._constraint_to_smt2(c)})")

        lines.append("(check-sat)")
        lines.append("(get-model)")

        return "\n".join(lines)

    @staticmethod
    def _constraint_to_smt2(constraint: str) -> str:
        """Crude translation of Python-style constraints to SMT-LIB2 syntax."""
        c = constraint.strip()
        # Handle common patterns
        c = c.replace("==", "=")
        c = c.replace("!=", "(not (= ...))")  # approximate
        c = c.replace("&&", "and")
        c = c.replace("||", "or")
        c = c.replace("<=", "<=")
        c = c.replace(">=", ">=")
        # Wrap in assertion-like form
        if not c.startswith("("):
            # Try to detect simple comparisons
            for op in ("<=", ">=", "=", "<", ">"):
                if op in c and not c.startswith("("):
                    parts = c.split(op, 1)
                    if len(parts) == 2:
                        smt_op = {"<=": "<=", ">=": ">=", "=": "=", "<": "<", ">": ">"}[op]
                        c = f"({smt_op} {parts[0].strip()} {parts[1].strip()})"
                    break
        return c


# ── Self-test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("SOLVER SELF-TEST")
    print("=" * 60)

    s = Solver()
    print(f"Z3 available: {s.available}")

    # ── Test solve_constraints ────────────────────────────────────────
    print("\n── solve_constraints ──")
    result = s.solve_constraints(
        variables={"x": "Int", "y": "Int"},
        constraints=["x > 0", "y > x", "x + y < 10"],
    )
    print(f"Status: {result.status}")
    if result.status == "sat":
        print(f"Assignment: {result.assignment}")
        assert result.assignment["x"] > 0
        assert result.assignment["y"] > result.assignment["x"]
        assert result.assignment["x"] + result.assignment["y"] < 10
    elif result.status == "z3_unavailable":
        print("(Z3 not installed — fallback mode)")

    # ── Test unsatisfiable ────────────────────────────────────────────
    print("\n── Unsatisfiable ──")
    result2 = s.solve_constraints(
        variables={"x": "Int"},
        constraints=["x > 5", "x < 3"],
    )
    print(f"Status: {result2.status}")
    assert result2.status in ("unsat", "z3_unavailable")

    # ── Test optimize ─────────────────────────────────────────────────
    print("\n── optimize (maximize) ──")
    opt = s.optimize(
        objective="x + y",
        constraints=["x >= 0", "y >= 0", "x + y <= 20", "x <= 10"],
        variables={"x": "Int", "y": "Int"},
        maximize=True,
    )
    print(f"Status: {opt.status}")
    if opt.status == "sat":
        print(f"Assignment: {opt.assignment}, objective={opt.objective_value}")
        assert opt.objective_value is not None

    # ── Test check_sat ────────────────────────────────────────────────
    print("\n── check_sat ──")
    status = s.check_sat("And(x > 0, x < 10)", variables={"x": "Int"})
    print(f"Satisfiable: {status}")
    assert status in ("sat", "z3_unavailable")

    status2 = s.check_sat("And(x > 10, x < 5)", variables={"x": "Int"})
    print(f"Unsatisfiable: {status2}")
    assert status2 in ("unsat", "z3_unavailable")

    # ── Test to_smt2 (always works) ───────────────────────────────────
    print("\n── to_smt2 ──")
    smt2 = s.to_smt2(
        variables={"x": "Int", "y": "Int"},
        constraints=["x > 0", "y >= x", "x + y == 10"],
    )
    print(smt2[:300])
    assert "(declare-fun x () Int)" in smt2
    assert "(declare-fun y () Int)" in smt2
    assert "(check-sat)" in smt2

    # ── Test variable type inference ──────────────────────────────────
    print("\n── Variable inference ──")
    opt2 = s.optimize(
        objective="a + b",
        constraints=["a >= 0", "b >= 0", "a * 2 + b <= 100"],
        maximize=True,
    )
    print(f"Status: {opt2.status}")
    if opt2.status == "sat":
        print(f"Assignment: {opt2.assignment}, objective={opt2.objective_value}")

    print(f"\n{'✅' if s.available else '⚠️ '} Solver tests complete "
          f"({'Z3 available' if s.available else 'Z3 not installed — fallback verified'})")