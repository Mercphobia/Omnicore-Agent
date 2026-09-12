#!/usr/bin/env python3
"""DSL Compiler — custom domain-specific language compiler.
DNA: Lexicon (language construction).

Provides a minimal lexer + recursive-descent parser that compiles
a simple expression DSL (arithmetic, conditionals, loops) into an
AST (nested dict). The AST can then be executed against a context.

Grammar:
    program    → statement*
    statement  → let_stmt | if_stmt | while_stmt | for_stmt | expr_stmt
    let_stmt   → 'let' IDENT '=' expr
    if_stmt    → 'if' expr 'then' block ('else' block)?
    while_stmt → 'while' expr 'do' block
    for_stmt   → 'for' IDENT 'in' expr 'to' expr 'do' block
    block      → '{' statement* '}'
    expr_stmt  → expr
    expr       → comparison (('&&' | '||') comparison)*
    comparison → arith (('==' | '!=' | '<' | '>' | '<='| '>=') arith)?
    arith      → term (('+' | '-') term)*
    term       → unary (('*' | '/' | '%') unary)*
    unary      → ('-' | '!') unary | primary
    primary    → NUMBER | STRING | IDENT | '(' expr ')' | IDENT '(' args? ')'
    args       → expr (',' expr)*
"""

from __future__ import annotations

import math
import operator
import re
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

@dataclass
class Token:
    type: str
    value: str
    line: int = 0
    col: int = 0


TOKEN_SPEC: list[tuple[str, str]] = [
    ("NUMBER", r"\d+(?:\.\d+)?"),
    ("STRING", r'"[^"]*"|\'[^\']*\''),
    ("IDENT", r"[a-zA-Z_]\w*"),
    # Multi-char operators (longer first)
    ("LE", r"<="),
    ("GE", r">="),
    ("EQ", r"=="),
    ("NE", r"!="),
    ("AND", r"&&"),
    ("OR", r"\|\|"),
    ("ASSIGN", r"="),
    ("LT", r"<"),
    ("GT", r">"),
    ("PLUS", r"\+"),
    ("MINUS", r"-"),
    ("STAR", r"\*"),
    ("SLASH", r"/"),
    ("PERCENT", r"%"),
    ("BANG", r"!"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("LBRACE", r"\{"),
    ("RBRACE", r"\}"),
    ("COMMA", r","),
    ("TO", r"\.\."),  # '..' for for-loop range
    ("SEMI", r";"),
    ("NEWLINE", r"\n"),
    ("SKIP", r"[ \t\r]+"),
    ("COMMENT", r"//[^\n]*"),
]


def tokenize(source: str) -> list[Token]:
    """Convert source string into a flat list of tokens (no NEWLINE/SKIP/COMMENT)."""
    tokens: list[Token] = []
    pos = 0
    line = 1
    col = 1

    while pos < len(source):
        match = None
        for tok_type, pattern in TOKEN_SPEC:
            regex = re.compile(pattern)
            match = regex.match(source, pos)
            if match:
                value = match.group(0)
                if tok_type not in ("SKIP", "COMMENT", "NEWLINE"):
                    tokens.append(Token(tok_type, value, line, col))
                if tok_type == "NEWLINE":
                    line += 1
                    col = 1
                else:
                    col += len(value)
                pos = match.end()
                break
        if match is None:
            raise SyntaxError(
                f"Illegal character {source[pos]!r} at line {line}, col {col}"
            )
    tokens.append(Token("EOF", "", line, col))
    return tokens


# ---------------------------------------------------------------------------
# Parser (recursive descent)
# ---------------------------------------------------------------------------

# Built-in functions available in the DSL
_BUILTINS: dict[str, Callable[..., Any]] = {
    "print": lambda *a: print(*a),
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sqrt": math.sqrt,
    "pow": pow,
    "sin": math.sin,
    "cos": math.cos,
    "range": lambda start, end: list(range(int(start), int(end) + 1)),
}


class Parser:
    """Recursive-descent parser for the OmniCore DSL."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _current(self) -> Token:
        return self.tokens[self.pos]

    def _peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        return self.tokens[idx] if idx < len(self.tokens) else self.tokens[-1]

    def _advance(self) -> Token:
        tok = self._current()
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def _expect(self, typ: str, value: str | None = None) -> Token:
        tok = self._current()
        if tok.type != typ or (value is not None and tok.value != value):
            raise SyntaxError(
                f"Line {tok.line}: expected {typ}"
                + (f" '{value}'" if value else "")
                + f", got {tok.type} '{tok.value}'"
            )
        return self._advance()

    def _match(self, typ: str, value: str | None = None) -> bool:
        tok = self._current()
        return tok.type == typ and (value is None or tok.value == value)

    # ------------------------------------------------------------------
    # program → statement*
    # ------------------------------------------------------------------
    def parse_program(self) -> dict[str, Any]:
        """Parse the full program into a root AST node."""
        statements: list[dict[str, Any]] = []
        while not self._match("EOF"):
            statements.append(self._parse_statement())
            # Allow optional semicolons between statements
            if self._match("SEMI"):
                self._advance()
        return {"type": "program", "body": statements}

    # ------------------------------------------------------------------
    # statement
    # ------------------------------------------------------------------
    def _parse_statement(self) -> dict[str, Any]:
        tok = self._current()
        if tok.type == "IDENT":
            if tok.value == "let":
                return self._parse_let()
            elif tok.value == "if":
                return self._parse_if()
            elif tok.value == "while":
                return self._parse_while()
            elif tok.value == "for":
                return self._parse_for()
        return self._parse_expr_stmt()

    def _parse_let(self) -> dict[str, Any]:
        self._expect("IDENT", "let")
        name = self._expect("IDENT").value
        self._expect("ASSIGN")
        value = self._parse_expr()
        return {"type": "let", "name": name, "value": value}

    def _parse_if(self) -> dict[str, Any]:
        self._expect("IDENT", "if")
        condition = self._parse_expr()
        self._expect("IDENT", "then")
        consequent = self._parse_block()
        alternate = None
        if self._match("IDENT", "else"):
            self._expect("IDENT", "else")
            alternate = self._parse_block()
        return {"type": "if", "condition": condition, "consequent": consequent, "alternate": alternate}

    def _parse_while(self) -> dict[str, Any]:
        self._expect("IDENT", "while")
        condition = self._parse_expr()
        self._expect("IDENT", "do")
        body = self._parse_block()
        return {"type": "while", "condition": condition, "body": body}

    def _parse_for(self) -> dict[str, Any]:
        self._expect("IDENT", "for")
        var = self._expect("IDENT").value
        self._expect("IDENT", "in")
        start = self._parse_expr()
        self._expect("TO")
        end = self._parse_expr()
        self._expect("IDENT", "do")
        body = self._parse_block()
        return {"type": "for", "var": var, "start": start, "end": end, "body": body}

    def _parse_block(self) -> dict[str, Any]:
        self._expect("LBRACE")
        stmts: list[dict[str, Any]] = []
        while not self._match("RBRACE") and not self._match("EOF"):
            stmts.append(self._parse_statement())
            if self._match("SEMI"):
                self._advance()
        self._expect("RBRACE")
        return {"type": "block", "body": stmts}

    def _parse_expr_stmt(self) -> dict[str, Any]:
        expr = self._parse_expr()
        return {"type": "expr_stmt", "expression": expr}

    # ------------------------------------------------------------------
    # expression levels
    # ------------------------------------------------------------------
    def _parse_expr(self) -> dict[str, Any]:
        return self._parse_logical_or()

    def _parse_logical_or(self) -> dict[str, Any]:
        left = self._parse_logical_and()
        while self._match("OR"):
            op = self._advance().value
            right = self._parse_logical_and()
            left = {"type": "binary", "operator": "||", "left": left, "right": right}
        return left

    def _parse_logical_and(self) -> dict[str, Any]:
        left = self._parse_comparison()
        while self._match("AND"):
            op = self._advance().value
            right = self._parse_comparison()
            left = {"type": "binary", "operator": "&&", "left": left, "right": right}
        return left

    def _parse_comparison(self) -> dict[str, Any]:
        left = self._parse_arith()
        if self._match("EQ") or self._match("NE") or self._match("LT") or self._match("GT") or self._match("LE") or self._match("GE"):
            op = self._advance().value
            right = self._parse_arith()
            left = {"type": "binary", "operator": op, "left": left, "right": right}
        return left

    def _parse_arith(self) -> dict[str, Any]:
        left = self._parse_term()
        while self._match("PLUS") or self._match("MINUS"):
            op = self._advance().value
            right = self._parse_term()
            left = {"type": "binary", "operator": op, "left": left, "right": right}
        return left

    def _parse_term(self) -> dict[str, Any]:
        left = self._parse_unary()
        while self._match("STAR") or self._match("SLASH") or self._match("PERCENT"):
            op = self._advance().value
            right = self._parse_unary()
            left = {"type": "binary", "operator": op, "left": left, "right": right}
        return left

    def _parse_unary(self) -> dict[str, Any]:
        if self._match("MINUS"):
            self._advance()
            operand = self._parse_unary()
            return {"type": "unary", "operator": "-", "operand": operand}
        if self._match("BANG"):
            self._advance()
            operand = self._parse_unary()
            return {"type": "unary", "operator": "!", "operand": operand}
        return self._parse_primary()

    def _parse_primary(self) -> dict[str, Any]:
        tok = self._current()

        if tok.type == "NUMBER":
            self._advance()
            raw = tok.value
            return {"type": "literal", "value": float(raw) if "." in raw else int(raw)}

        if tok.type == "STRING":
            self._advance()
            return {"type": "literal", "value": tok.value[1:-1]}  # strip quotes

        if tok.type == "IDENT":
            name = self._advance().value
            # Function call?
            if self._match("LPAREN"):
                self._advance()
                args: list[dict[str, Any]] = []
                if not self._match("RPAREN"):
                    args.append(self._parse_expr())
                    while self._match("COMMA"):
                        self._advance()
                        args.append(self._parse_expr())
                self._expect("RPAREN")
                return {"type": "call", "name": name, "arguments": args}
            return {"type": "ident", "name": name}

        if tok.type == "LPAREN":
            self._advance()
            expr = self._parse_expr()
            self._expect("RPAREN")
            return expr

        raise SyntaxError(
            f"Line {tok.line}: unexpected token {tok.type} '{tok.value}'"
        )


# ---------------------------------------------------------------------------
# Compiler (thin wrapper)
# ---------------------------------------------------------------------------

class DSLCompiler:
    """Compile and execute a simple expression DSL.

    Usage::

        compiler = DSLCompiler()
        compiler.define_grammar({"builtins": {"pow": lambda x, y: x ** y}})
        ast = compiler.compile(\"\"\"
            let x = 10
            let y = x + 5
            if y > 10 then {
                print(y)
            }
        \"\"\")
        compiler.execute(ast, {})
    """

    def __init__(self) -> None:
        self._builtins: dict[str, Callable[..., Any]] = dict(_BUILTINS)

    # ------------------------------------------------------------------
    def define_grammar(self, grammar_spec: dict[str, Any]) -> None:
        """Register additional built-in functions or grammar rules.

        *grammar_spec* is a dict with optional keys:
        - ``builtins``: dict of ``{name: callable}`` added to the execution
          environment.
        """
        if "builtins" in grammar_spec:
            self._builtins.update(grammar_spec["builtins"])

    # ------------------------------------------------------------------
    def compile(self, source_code: str) -> dict[str, Any]:
        """Tokenize + parse *source_code* into a nested-dict AST.

        Returns::

            {"type": "program", "body": [...]}
        """
        tokens = tokenize(source_code)
        parser = Parser(tokens)
        return parser.parse_program()

    # ------------------------------------------------------------------
    def execute(self, ast: dict[str, Any], context: dict[str, Any] | None = None) -> Any:
        """Walk *ast* and return the result of the final expression.

        *context* is a dict of variable bindings (most callers pass ``{}``
        and let the program populate it via ``let`` statements).

        Returns the last expression value evaluated, or ``None``.
        """
        if context is None:
            context = {}
        return _Evaluator(self._builtins, context).eval_node(ast)


# ---------------------------------------------------------------------------
# AST evaluator
# ---------------------------------------------------------------------------

_OPS: dict[str, Callable[[Any, Any], Any]] = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "%": operator.mod,
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    ">": operator.gt,
    "<=": operator.le,
    ">=": operator.ge,
    "&&": lambda a, b: bool(a) and bool(b),
    "||": lambda a, b: bool(a) or bool(b),
}


class _Evaluator:
    """Walk the AST and compute results."""

    def __init__(
        self,
        builtins: dict[str, Callable[..., Any]],
        context: dict[str, Any],
    ) -> None:
        self._builtins = builtins
        self._ctx = context
        self._last: Any = None

    def eval_node(self, node: dict[str, Any]) -> Any:
        typ = node["type"]
        method = getattr(self, f"_eval_{typ}", None)
        if method is None:
            raise ValueError(f"Unknown AST node type: {typ}")
        return method(node)

    # -- literals -------------------------------------------------------
    def _eval_literal(self, n: dict[str, Any]) -> Any:
        self._last = n["value"]
        return self._last

    def _eval_ident(self, n: dict[str, Any]) -> Any:
        name = n["name"]
        if name in self._ctx:
            self._last = self._ctx[name]
            return self._last
        if name in self._builtins:
            self._last = self._builtins[name]
            return self._last
        raise NameError(f"Undefined variable: {name}")

    # -- expressions ----------------------------------------------------
    def _eval_binary(self, n: dict[str, Any]) -> Any:
        left = self.eval_node(n["left"])
        right = self.eval_node(n["right"])
        op = n["operator"]
        try:
            self._last = _OPS[op](left, right)
        except ZeroDivisionError:
            raise ZeroDivisionError("Division by zero in DSL expression")
        return self._last

    def _eval_unary(self, n: dict[str, Any]) -> Any:
        val = self.eval_node(n["operand"])
        if n["operator"] == "-":
            self._last = -val
        elif n["operator"] == "!":
            self._last = not val
        return self._last

    def _eval_call(self, n: dict[str, Any]) -> Any:
        fn_name = n["name"]
        args = [self.eval_node(a) for a in n["arguments"]]
        if fn_name in self._builtins:
            self._last = self._builtins[fn_name](*args)
            return self._last
        if fn_name in self._ctx and callable(self._ctx[fn_name]):
            self._last = self._ctx[fn_name](*args)
            return self._last
        raise NameError(f"Undefined function: {fn_name}")

    # -- statements -----------------------------------------------------
    def _eval_program(self, n: dict[str, Any]) -> Any:
        for stmt in n["body"]:
            self.eval_node(stmt)
        return self._last

    def _eval_block(self, n: dict[str, Any]) -> Any:
        for stmt in n["body"]:
            self.eval_node(stmt)
        return self._last

    def _eval_expr_stmt(self, n: dict[str, Any]) -> Any:
        return self.eval_node(n["expression"])

    def _eval_let(self, n: dict[str, Any]) -> Any:
        val = self.eval_node(n["value"])
        self._ctx[n["name"]] = val
        self._last = val
        return val

    def _eval_if(self, n: dict[str, Any]) -> Any:
        cond = self.eval_node(n["condition"])
        if cond:
            return self.eval_node(n["consequent"])
        if n.get("alternate"):
            return self.eval_node(n["alternate"])
        return None

    def _eval_while(self, n: dict[str, Any]) -> Any:
        while self.eval_node(n["condition"]):
            self.eval_node(n["body"])
        return self._last

    def _eval_for(self, n: dict[str, Any]) -> Any:
        start = int(self.eval_node(n["start"]))
        end = int(self.eval_node(n["end"]))
        var = n["var"]
        for i in range(start, end + 1):
            self._ctx[var] = i
            self.eval_node(n["body"])
        return self._last


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    compiler = DSLCompiler()

    # --- Arithmetic ---
    ast = compiler.compile("1 + 2 * 3")
    assert compiler.execute(ast, {}) == 7, "arithmetic failed"

    ast = compiler.compile("(1 + 2) * 3")
    assert compiler.execute(ast, {}) == 9, "parenthesised arithmetic failed"

    # --- Let + expressions ---
    ast = compiler.compile("""
        let x = 10
        let y = x + 5
        y * 2
    """)
    assert compiler.execute(ast, {}) == 30, "let binding failed"

    # --- If-then-else ---
    ast = compiler.compile("""
        let a = 5
        if a > 3 then { a * 2 } else { a }
    """)
    assert compiler.execute(ast, {}) == 10, "if-then failed"

    ast = compiler.compile("""
        let a = 2
        if a > 3 then { a * 2 } else { a }
    """)
    assert compiler.execute(ast, {}) == 2, "if-else failed"

    # --- While loop ---
    ast = compiler.compile("""
        let i = 0
        let sum = 0
        while i < 5 do {
            let sum = sum + i
            let i = i + 1
        }
        sum
    """)
    assert compiler.execute(ast, {}) == 10, "while loop failed"  # 0+1+2+3+4

    # --- For loop ---
    ast = compiler.compile("""
        let total = 0
        for i in 1 .. 5 do {
            let total = total + i
        }
        total
    """)
    assert compiler.execute(ast, {}) == 15, "for loop failed"  # 1+2+3+4+5

    # --- Comparisons ---
    ast = compiler.compile("3 > 2 && 1 < 5")
    assert compiler.execute(ast, {}) is True, "comparison failed"

    ast = compiler.compile("3 < 2 || 5 > 1")
    assert compiler.execute(ast, {}) is True, "logical-or failed"

    # --- Unary ---
    ast = compiler.compile("-5 + 10")
    assert compiler.execute(ast, {}) == 5, "unary minus failed"

    ast = compiler.compile("!0")
    assert compiler.execute(ast, {}) is True, "unary not failed"

    # --- Built-in functions ---
    ast = compiler.compile('sqrt(16)')
    assert compiler.execute(ast, {}) == 4.0, "sqrt failed"

    ast = compiler.compile('len("hello")')
    assert compiler.execute(ast, {}) == 5, "len failed"

    # --- Custom grammar ---
    compiler.define_grammar({"builtins": {"cube": lambda x: x ** 3}})
    ast = compiler.compile("cube(3)")
    assert compiler.execute(ast, {}) == 27, "custom builtin failed"

    # --- Error handling ---
    try:
        compiler.compile("1 +")
    except SyntaxError:
        pass
    else:
        raise AssertionError("should have raised SyntaxError")

    try:
        ast = compiler.compile("undefined_var")
        compiler.execute(ast, {})
    except NameError:
        pass
    else:
        raise AssertionError("should have raised NameError")

    print("All DSL compiler tests passed.")