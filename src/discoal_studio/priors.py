# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""Prior distributions and a tiny safe expression evaluator.

Bounds may be numbers or short expressions over values already drawn for the
same file, e.g. ``"1/(2*N)"`` for the lowest possible starting frequency.
"""
from __future__ import annotations

import ast
import math
import operator
import random
from typing import Literal, Union

from pydantic import BaseModel, model_validator

Number = Union[float, int, str]

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
}


def evaluate(expr: Number, env: dict[str, float]) -> float:
    """Evaluate a number or an arithmetic expression using names from ``env``."""
    if isinstance(expr, (int, float)):
        return expr
    try:
        return float(expr)
    except ValueError:
        pass

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise ValueError(f"'{node.id}' is not known yet (known: {', '.join(env) or 'none'})")
            return env[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.operand))
        raise ValueError(f"unsupported expression: {expr!r}")

    return walk(ast.parse(str(expr), mode="eval"))


class Prior(BaseModel):
    """One parameter's distribution.

    fixed                   value
    uniform                 low, high          (real numbers)
    uniform_int             low, high          (whole numbers, both ends included)
    loguniform              low, high          (log is uniform; each x2 step equally likely)
    truncated_exponential   mean, upper        (redraw while above upper)
    """
    dist: Literal["fixed", "uniform", "uniform_int", "loguniform", "truncated_exponential"]
    value: Number | None = None
    low: Number | None = None
    high: Number | None = None
    mean: Number | None = None
    upper: Number | None = None

    @model_validator(mode="after")
    def _needs(self):
        need = {"fixed": ["value"], "uniform": ["low", "high"], "uniform_int": ["low", "high"],
                "loguniform": ["low", "high"], "truncated_exponential": ["mean", "upper"]}[self.dist]
        missing = [k for k in need if getattr(self, k) is None]
        if missing:
            raise ValueError(f"{self.dist} prior needs {', '.join(missing)}")
        return self

    @property
    def is_random(self) -> bool:
        return self.dist != "fixed"

    def sample(self, rng: random.Random, env: dict[str, float]) -> float:
        # The call pattern below must stay as is: it reproduces make_dataset.py draw for draw.
        if self.dist == "fixed":
            return evaluate(self.value, env)
        if self.dist == "uniform_int":
            return rng.randint(int(evaluate(self.low, env)), int(evaluate(self.high, env)))
        if self.dist == "uniform":
            return rng.uniform(evaluate(self.low, env), evaluate(self.high, env))
        if self.dist == "loguniform":
            lo, hi = evaluate(self.low, env), evaluate(self.high, env)
            if lo <= 0 or hi <= 0:
                raise ValueError("loguniform bounds must be > 0")
            return math.exp(rng.uniform(math.log(lo), math.log(hi)))
        mean, upper = evaluate(self.mean, env), evaluate(self.upper, env)
        x = rng.expovariate(1 / mean)
        while x > upper:
            x = rng.expovariate(1 / mean)
        return x

    def describe(self) -> str:
        return {
            "fixed": lambda: f"{self.value}",
            "uniform": lambda: f"U({self.low}, {self.high})",
            "uniform_int": lambda: f"U{{{self.low}..{self.high}}}",
            "loguniform": lambda: f"logU({self.low}, {self.high})",
            "truncated_exponential": lambda: f"Exp(mean {self.mean}) ≤ {self.upper}",
        }[self.dist]()


def fixed(v: Number) -> Prior:
    return Prior(dist="fixed", value=v)
