"""Calculator tool (Appendix B §B.3.1).

Safe AST evaluator — no raw `eval` (PRD Decision #8), whitelisted operators
only, plus a pow guard so a tiny expression can't DoS the sidecar.
"""

import ast
import operator as op

from pydantic import BaseModel, Field

from .base import ExecutionContext, Tool
from .registry import register


class CalculatorArgs(BaseModel):
    expression: str = Field(
        description="A mathematical expression to evaluate, e.g. '2 * (3 + 4)'. "
                    "No variables, no function calls, no names."
    )


# Safe evaluator (PRD Decision #8: no raw eval). Whitelisted operators only.
_BINOPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
    ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod, ast.Pow: op.pow,
}
_UNARYOPS = {ast.UAdd: op.pos, ast.USub: op.neg}

# Guard against resource-exhaustion via exponentiation. `2 ** (10 ** 9)` is a
# tiny expression that would otherwise pin a CPU and blow up memory building the
# integer — "safe evaluator" (Decision #8) means safe from DoS, not just from
# `eval`. We cap both the exponent and the base magnitude before computing pow.
_MAX_POW_EXPONENT = 1000
_MAX_POW_BASE = 1e6


def _guarded_pow(base: float, exponent: float) -> float:
    if abs(exponent) > _MAX_POW_EXPONENT or abs(base) > _MAX_POW_BASE:
        raise ValueError("exponent or base too large")
    return op.pow(base, exponent)


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("only numeric constants are allowed")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Pow):
            return _guarded_pow(left, right)
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression element")


def calculator(args: CalculatorArgs, ctx: ExecutionContext) -> str:
    try:
        tree = ast.parse(args.expression, mode="eval")
        result = _safe_eval(tree.body)
    except ZeroDivisionError:
        return "Error: division by zero"
    except OverflowError:
        return "Error: result too large to compute"
    except (ValueError, SyntaxError, TypeError):
        return "Error: could not evaluate that expression"
    return str(result)


register(Tool(
    name="calculator",
    description="Evaluate a math expression. No variables, no function calls.",
    args_model=CalculatorArgs,
    handler=calculator,
))
