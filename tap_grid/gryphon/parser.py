"""TAP gryphon language parser.

Converts gryphon text (str or list[str]) into a GryphonAST using lark.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from lark import Lark, Token, Transformer, UnexpectedInput, v_args
from lark.exceptions import VisitError

from tap_grid.gryphon.ast_nodes import (
    AggregateCall,
    AggregateReturnItem,
    AndPred,
    Comparison,
    DotStep,
    EdgePattern,
    FieldPath,
    GryphonAST,
    InComparison,
    IndexStep,
    IsNullComparison,
    KeyStep,
    LimitClause,
    LookupClause,
    MatchClause,
    NodePattern,
    NotExistsClause,
    NotPred,
    NowRef,
    ObservationComparison,
    OptionalMatchClause,
    OrderByClause,
    OrderByItem,
    OrPred,
    ParamNullTest,
    ParamRef,
    PathPattern,
    ReturnClause,
    ReturnItem,
    TemporalComparison,
    TemporalOffset,
    WhereClause,
    WildcardStep,
)

_GRAMMAR_PATH = os.path.join(os.path.dirname(__file__), "grammar.lark")

with open(_GRAMMAR_PATH) as _f:
    _GRAMMAR_TEXT = _f.read()

# Build the parser once at module load. LALR(1) is fast; ambiguity=resolve
# handles the OR/AND/NOT precedence rules in the grammar.
_PARSER = Lark(
    _GRAMMAR_TEXT,
    parser="earley",
    ambiguity="resolve",
    propagate_positions=False,
)


_TEMPORAL_OPS = ("<", "<=", ">", ">=")

_ARITHMETIC_REFUSAL = (
    "Arithmetic in {where} is not supported: a date-time offset is available only as a WHERE comparison, "
    "e.g. WHERE t.data.opened_at + hours(12) < now()."
)


class GryphonParseError(Exception):
    """Raised when gryphon text cannot be parsed.

    Attributes:
        message: Human-readable description.
        line: Line number (1-based) if available.
        col: Column number (1-based) if available.
    """

    def __init__(self, message: str, line: int | None = None, col: int | None = None) -> None:
        self.message = message
        self.line = line
        self.col = col
        loc = f" (line {line}, col {col})" if line is not None else ""
        super().__init__(f"Gryphon parse error{loc}: {message}")


# ---------------------------------------------------------------------------
# Transformer-internal markers
# ---------------------------------------------------------------------------
#
# node_body and edge_body parse into a handful of optional children — variable
# name, label, inline props, hop range — and lark flattens identically-typed
# children, so we need a way to distinguish "NAME that appeared BEFORE the
# colon" from "NAME that appeared AFTER the colon" in the transformer. These
# marker str-subclasses carry that distinction out of the sub-rule.


class _VarMarker(str):
    """A NAME token that appeared in the variable position of a node/edge body."""


class _LabelMarker(str):
    """A NAME token that appeared in the label/type position (after the colon)."""


# ---------------------------------------------------------------------------
# Lark transformer
# ---------------------------------------------------------------------------


@v_args(inline=True)
class _ASTTransformer(Transformer):
    """Transform a lark parse tree into TAP AST dataclasses."""

    # -- start / clauses --

    def start(self, *clauses: Any) -> GryphonAST:
        match_clauses = [c for c in clauses if isinstance(c, MatchClause)]
        optional_match_clauses = [c for c in clauses if isinstance(c, OptionalMatchClause)]
        where_clauses = [c for c in clauses if isinstance(c, WhereClause)]
        return_clauses = [c for c in clauses if isinstance(c, ReturnClause)]
        not_exists_clauses = [c for c in clauses if isinstance(c, NotExistsClause)]
        order_by_clauses = [c for c in clauses if isinstance(c, OrderByClause)]
        limit_clauses = [c for c in clauses if isinstance(c, LimitClause)]
        lookup_clauses = [c for c in clauses if isinstance(c, LookupClause)]

        if not match_clauses:
            raise GryphonParseError("At least one MATCH clause is required.")
        # WHERE / RETURN / ORDER BY / LIMIT are all single-clause. A duplicate
        # is an authoring mistake; silently keeping the first and dropping the
        # rest is a query that lies about what it ran. Reject loudly instead.
        if len(where_clauses) > 1:
            raise GryphonParseError(
                "Only one WHERE clause is allowed per query — combine predicates with AND "
                "(Gryphon has a single global WHERE, scoped per variable)."
            )
        if len(return_clauses) > 1:
            raise GryphonParseError("Only one RETURN clause is allowed per query.")
        if len(order_by_clauses) > 1:
            raise GryphonParseError("Only one ORDER BY clause is allowed per query.")
        if len(limit_clauses) > 1:
            raise GryphonParseError("Only one LIMIT clause is allowed per query.")

        where = where_clauses[0] if where_clauses else None
        ret = return_clauses[0] if return_clauses else ReturnClause(items=None)

        ast = GryphonAST(
            match_clauses=tuple(match_clauses),
            where_clause=where,
            return_clause=ret,
            not_exists_clauses=tuple(not_exists_clauses),
            order_by=order_by_clauses[0] if order_by_clauses else None,
            limit=limit_clauses[0] if limit_clauses else None,
            optional_match_clauses=tuple(optional_match_clauses),
            lookup_clauses=tuple(lookup_clauses),
        )
        _validate_lookups(ast)
        return ast

    def clause(self, inner: Any) -> Any:
        return inner

    def edge_pattern(self, inner: Any) -> Any:
        """Pass-through: unwraps the Tree wrapper lark adds for unaliased single-child rules."""
        return inner

    def predicate(self, inner: Any) -> Any:
        """Pass-through: unwraps Tree wrapper for the unaliased `comparison` alternative."""
        return inner

    # -- MATCH --

    def match_clause(self, *args: Any) -> MatchClause:
        path_var: str | None = None
        patterns: list[PathPattern] = []
        for a in args:
            if isinstance(a, str):
                path_var = a
            elif isinstance(a, PathPattern):
                patterns.append(a)
        return MatchClause(path_var=path_var, patterns=tuple(patterns))

    def path_var(self, name: Token) -> str:
        return str(name)

    def optional_match_clause(self, *patterns: Any) -> OptionalMatchClause:
        return OptionalMatchClause(patterns=tuple(p for p in patterns if isinstance(p, PathPattern)))

    def pattern(self, *args: Any) -> PathPattern:
        nodes = [a for a in args if isinstance(a, NodePattern)]
        edges = [a for a in args if isinstance(a, EdgePattern)]
        return PathPattern(nodes=tuple(nodes), edges=tuple(edges))

    def node_pattern(self, body: Any) -> NodePattern:
        return body

    def node_body(self, *args: Any) -> NodePattern:
        variable: str | None = None
        label: str | None = None
        props: dict[str, Any] = {}
        for a in args:
            if isinstance(a, _VarMarker):
                variable = str(a)
            elif isinstance(a, _LabelMarker):
                label = str(a)
            elif isinstance(a, dict):
                props = a
        return NodePattern(variable=variable, label=label, inline_props=props)

    def node_body_var(self, name: Token) -> _VarMarker:
        return _VarMarker(str(name))

    def node_body_label(self, name: Token) -> _LabelMarker:
        return _LabelMarker(str(name))

    def outbound_edge(self, body: Any) -> EdgePattern:
        return EdgePattern(
            variable=body.variable,
            edge_type=body.edge_type,
            direction="out",
            min_hops=body.min_hops,
            max_hops=body.max_hops,
            inline_props=body.inline_props,
        )

    def inbound_edge(self, body: Any) -> EdgePattern:
        return EdgePattern(
            variable=body.variable,
            edge_type=body.edge_type,
            direction="in",
            min_hops=body.min_hops,
            max_hops=body.max_hops,
            inline_props=body.inline_props,
        )

    def undirected_edge(self, body: Any) -> EdgePattern:
        return EdgePattern(
            variable=body.variable,
            edge_type=body.edge_type,
            direction="any",
            min_hops=body.min_hops,
            max_hops=body.max_hops,
            inline_props=body.inline_props,
        )

    def edge_body(self, *args: Any) -> EdgePattern:
        variable: str | None = None
        edge_type: str | None = None
        min_hops = 1
        max_hops = 1
        props: dict[str, Any] = {}
        for a in args:
            if isinstance(a, _VarMarker):
                variable = str(a)
            elif isinstance(a, _LabelMarker):
                edge_type = str(a)
            elif isinstance(a, tuple):  # hop_range
                min_hops, max_hops = a
            elif isinstance(a, dict):
                props = a
        # direction is set by the parent edge_pattern rule
        return EdgePattern(
            variable=variable,
            edge_type=edge_type,
            direction="any",
            min_hops=min_hops,
            max_hops=max_hops,
            inline_props=props,
        )

    def edge_body_var(self, name: Token) -> _VarMarker:
        return _VarMarker(str(name))

    def edge_body_type(self, name: Token) -> _LabelMarker:
        return _LabelMarker(str(name))

    def hop_range(self, lo: Token, hi: Token) -> tuple[int, int]:
        return int(lo), int(hi)

    def inline_props(self, *pairs: Any) -> dict[str, Any]:
        # Preserve apply-or-reject before map reduction and AST param discovery:
        # dict(pairs) alone would erase the first predicate (and its $param).
        props: dict[str, Any] = {}
        for key, value in pairs:
            if key in props:
                raise GryphonParseError(
                    f"Duplicate inline property key {key!r}. Each key must appear once; "
                    "use explicit WHERE predicates joined with AND for repeated constraints."
                )
            props[key] = value
        return props

    def prop_pair(self, name: Token, value: Any) -> tuple[str, Any]:
        return str(name), value

    # -- WHERE --

    def where_clause(self, predicate: Any) -> WhereClause:
        return WhereClause(predicate=predicate)

    def and_pred(self, left: Any, right: Any) -> AndPred:
        return AndPred(left=left, right=right)

    def or_pred(self, left: Any, right: Any) -> OrPred:
        return OrPred(left=left, right=right)

    def not_pred(self, operand: Any) -> NotPred:
        return NotPred(operand=operand)

    def paren_pred(self, inner: Any) -> Any:
        return inner

    def comparison(self, fp: FieldPath, op: Token, value: Any) -> Comparison:
        # Lower-casing normalizes the substring keywords (STARTS_WITH -> starts_with,
        # case-insensitive in the grammar) to their AST `op` form; the symbolic
        # COMPARE_OP tokens (=, !=, <, ...) are unaffected by .lower().
        return Comparison(field_path=fp, op=str(op).lower(), value=value)

    def regex_comparison(self, fp: FieldPath, value: Any) -> Comparison:
        # The `=~` literal in the grammar carries no token, so this transformer
        # receives just the field_path and the value. Op is normalized to the
        # AST identifier "regex" — chosen over carrying the raw "=~" symbol so
        # the executor's op→lookup map stays keyed on word-form identifiers
        # alongside "starts_with" / "ends_with" / "contains". Per
        # req-grid-traversal-lang-regex.
        return Comparison(field_path=fp, op="regex", value=value)

    def in_comparison(self, fp: FieldPath, values: tuple[Any, ...]) -> InComparison:
        return InComparison(field_path=fp, values=values)

    def is_null(self, fp: FieldPath) -> IsNullComparison:
        # Both `_IS_KW` and `_NULL_KW` are underscore-prefixed and so are
        # discarded by lark — only the field_path child reaches the transformer.
        return IsNullComparison(field_path=fp, negated=False)

    def is_not_null(self, fp: FieldPath) -> IsNullComparison:
        # `_IS_KW`, `_NOT_KW`, and `_NULL_KW` are all underscore-prefixed and
        # discarded — only the field_path child reaches the transformer. A
        # separate rule label (vs. an optional `_NOT_KW`) is what lets the
        # transformer recover the negated flag at all (a discarded optional
        # gives the method no signal that NOT was present).
        return IsNullComparison(field_path=fp, negated=True)

    def is_known(self, fp: FieldPath) -> ObservationComparison:
        # `_IS_KW` and `_KNOWN_KW` are underscore-prefixed and discarded — only
        # the field_path child reaches the transformer. Separate rule labels
        # (is_known / is_unknown) recover the kind, exactly as is_null/is_not_null.
        return ObservationComparison(field_path=fp, kind="known")

    def is_unknown(self, fp: FieldPath) -> ObservationComparison:
        return ObservationComparison(field_path=fp, kind="unknown")

    def value_list(self, *values: Any) -> tuple[Any, ...]:
        return values

    # -- LOOKUP / temporal offset (req-grid-traversal-lang-temporal-offset) --

    def lookup_clause(self, variable: Token, label: Token, props: dict[str, Any]) -> LookupClause:
        # _LOOKUP_KW is discarded; the two NAME children are the variable then the label.
        return LookupClause(variable=str(variable), label=str(label), props=props)

    def offset_add(self, base: FieldPath, hours: Any) -> TemporalOffset:
        return TemporalOffset(base=base, sign="+", hours=hours)

    def offset_sub(self, base: FieldPath, hours: Any) -> TemporalOffset:
        return TemporalOffset(base=base, sign="-", hours=hours)

    def hours_term(self, arg: Any) -> Any:
        # _HOURS_KW is discarded; the child is a FieldPath, an INT token or a ParamRef.
        if isinstance(arg, Token):
            return int(arg)
        return arg

    def now_ref(self) -> NowRef:
        return NowRef()

    def temporal_operand(self, inner: Any) -> Any:
        return inner

    def temporal_comparison(self, offset: TemporalOffset, op: Token, operand: Any) -> TemporalComparison:
        if str(op) not in _TEMPORAL_OPS:
            raise GryphonParseError(
                f"'{op}' is not supported on a temporal offset comparison: equality on a computed instant is "
                f"not offered. Use one of {', '.join(_TEMPORAL_OPS)}."
            )
        return TemporalComparison(offset=offset, op=str(op), operand=operand)  # type: ignore[arg-type]

    def arithmetic_item(self, *_parts: Any) -> Any:
        raise GryphonParseError(_ARITHMETIC_REFUSAL.format(where="RETURN"))

    def arithmetic_order_item(self, *_parts: Any) -> Any:
        raise GryphonParseError(_ARITHMETIC_REFUSAL.format(where="ORDER BY"))

    # -- Field paths --

    def field_path(self, name: Token, *steps: Any) -> FieldPath:
        return FieldPath(variable=str(name), steps=tuple(steps))

    def field_step(self, step: Any) -> Any:
        return step

    def dot_step(self, name: Token) -> DotStep:
        return DotStep(name=str(name))

    def key_step(self, key: Token) -> KeyStep:
        return KeyStep(key=str(key)[1:-1])  # strip surrounding quotes

    def index_step(self, idx: Token) -> IndexStep:
        return IndexStep(index=int(idx))

    def wildcard_step(self, _star: Token) -> WildcardStep:
        return WildcardStep()

    # -- NOT EXISTS --

    def not_exists_clause(self, *args: Any) -> NotExistsClause:
        mc = next((a for a in args if isinstance(a, MatchClause)), None)
        wc = next((a for a in args if isinstance(a, WhereClause)), None)
        if mc is None:
            raise GryphonParseError("NOT EXISTS block requires a MATCH clause.")
        return NotExistsClause(match_clause=mc, where_clause=wc)

    # -- ORDER BY / LIMIT --

    def order_by_clause(self, *items: Any) -> OrderByClause:
        return OrderByClause(items=tuple(items))

    def order_item(self, path: Any, *direction: Any) -> OrderByItem:
        # `direction` is the optional order_dir child: () for the default
        # ascending case, or ("asc",) / ("desc",) when written explicitly.
        # `path` is a FieldPath produced by the field_path transformer —
        # bare-name terms (`ORDER BY label`) come through as FieldPath with
        # zero steps, full-path terms (`ORDER BY n.data.fetched_at`) carry
        # the dot-steps. Per req-grid-gryphon-order-by-envelope.
        descending = bool(direction) and direction[0] == "desc"
        return OrderByItem(path=path, descending=descending)

    def asc(self) -> str:
        # The _ASC_KW / _DESC_KW terminals are underscore-prefixed and so are
        # discarded by lark — these alias methods take no token child.
        return "asc"

    def desc(self) -> str:
        return "desc"

    def limit_clause(self, count: Token) -> LimitClause:
        return LimitClause(count=int(count))

    # -- RETURN --

    def return_clause(self, *items: Any) -> ReturnClause:
        return ReturnClause(items=tuple(items))

    def field_item(self, *args: Any) -> ReturnItem:
        path = args[0]
        alias = str(args[1]) if len(args) > 1 else None
        return ReturnItem(path=path, alias=alias)

    def aggregate_item(self, aggregate: AggregateCall, alias: Any) -> AggregateReturnItem:
        return AggregateReturnItem(aggregate=aggregate, alias=str(alias))

    # -- aggregates Gryphon does not implement: refuse them by name ---------------

    _SUPPORTED_AGGREGATES = "COUNT, MIN and MAX"

    def unsupported_item(self, *_parts: Any) -> Any:
        raise AssertionError("unsupported aggregates raise in their own rule")  # pragma: no cover

    def unsupported_aggregate(self, inner: Any) -> Any:  # pragma: no cover - alias rules below fire
        return inner

    def unsupported_function(self, name: Token, *_argument: Any) -> Any:
        fn = str(name).upper()
        raise GryphonParseError(
            f"{fn} is not a supported aggregate. The supported aggregates are {self._SUPPORTED_AGGREGATES}: "
            "COUNT(var), MIN(var.data.<field>), MAX(var.data.<field>)."
        )

    def unsupported_count_star(self, *_star: Any) -> Any:
        raise GryphonParseError(
            "COUNT(*) is not supported: count a bound variable instead, e.g. COUNT(n). "
            f"The supported aggregates are {self._SUPPORTED_AGGREGATES}."
        )

    def unsupported_count_distinct(self, _path: Any) -> Any:
        raise GryphonParseError(
            "COUNT(DISTINCT ...) is not supported: use COUNT(var), which counts every match. "
            f"The supported aggregates are {self._SUPPORTED_AGGREGATES}."
        )

    def count_call(self, path: FieldPath) -> AggregateCall:
        # The _COUNT_KW terminal is discarded by lark so the only child here is
        # the field_path argument.
        return AggregateCall(function="count", argument=path)

    def min_call(self, path: FieldPath) -> AggregateCall:
        return self._extremum_call("min", path)

    def max_call(self, path: FieldPath) -> AggregateCall:
        return self._extremum_call("max", path)

    @staticmethod
    def _extremum_call(function: Literal["min", "max"], path: FieldPath) -> AggregateCall:
        # req-grid-gryphon-minmax-2: the extremum of a whole entity has no meaning,
        # so a bare variable is refused here -- at parse time, before any execution
        # path (or OPTIONAL MATCH scoreboard) can see it -- naming the accepted form.
        if not path.steps:
            name = function.upper()
            raise GryphonParseError(
                f"{name}({path.variable}) is not supported: {name} takes a field path, "
                f"e.g. {name}({path.variable}.data.<field>), not a bare variable."
            )
        return AggregateCall(function=function, argument=path)

    # -- Values --

    def string_val(self, s: Token) -> str:
        raw = str(s)
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")

    def number_val(self, n: Token) -> int | float:
        s = str(n)
        return float(s) if "." in s else int(s)

    def param_ref(self, name: Token) -> ParamRef:
        return ParamRef(name=str(name))

    def param_is_null(self, ref: ParamRef) -> ParamNullTest:
        """`$p IS NULL` — a predicate about an INPUT, not about graph data."""
        return ParamNullTest(param=ref.name, negated=False)

    def param_is_not_null(self, ref: ParamRef) -> ParamNullTest:
        """`$p IS NOT NULL`."""
        return ParamNullTest(param=ref.name, negated=True)

    def true_val(self, _token: Token) -> bool:
        # @v_args(inline=True) passes the matched `/true/i` token as a child —
        # the method must accept it (string_val / number_val likewise).
        return True

    def false_val(self, _token: Token) -> bool:
        return False

    def null_val(self) -> None:
        # `_NULL_KW` is underscore-prefixed and so discarded by lark — the
        # method takes no token child. The terminal is shared with
        # `is_null` / `is_not_null` so the lexer doesn't see two different
        # rules matching `null` (req-grid-traversal-lang-is-null).
        return None

    def value(self, inner: Any) -> Any:
        return inner


_TRANSFORMER = _ASTTransformer()


# ---------------------------------------------------------------------------
# LOOKUP scope validation (req-grid-traversal-lang-temporal-offset, GRY-SEM-6)
# ---------------------------------------------------------------------------


def _predicate_leaves(pred: Any) -> Any:
    """Yield every leaf of a predicate tree (AND / OR / NOT are not leaves)."""
    if isinstance(pred, (AndPred, OrPred)):
        yield from _predicate_leaves(pred.left)
        yield from _predicate_leaves(pred.right)
    elif isinstance(pred, NotPred):
        yield from _predicate_leaves(pred.operand)
    elif pred is not None:
        yield pred


def _match_variables(ast: GryphonAST) -> set[str]:
    """Every variable a MATCH, OPTIONAL MATCH or NOT EXISTS block binds."""
    names: set[str] = set()
    pattern_groups: list[tuple[PathPattern, ...]] = [mc.patterns for mc in ast.match_clauses]
    pattern_groups += [omc.patterns for omc in ast.optional_match_clauses]
    pattern_groups += [nec.match_clause.patterns for nec in ast.not_exists_clauses]
    for mc in (*ast.match_clauses, *(nec.match_clause for nec in ast.not_exists_clauses)):
        if mc.path_var:
            names.add(mc.path_var)
    for patterns in pattern_groups:
        for pattern in patterns:
            # An unnamed labelled node binds its label as the variable (the executor's `v = variable or label`).
            names.update(bound for n in pattern.nodes if (bound := n.variable or n.label))
            names.update(e.variable for e in pattern.edges if e.variable)
    return names


def _validate_lookups(ast: GryphonAST) -> None:
    """Refuse every LOOKUP misuse that is decidable from the parsed text alone.

    A lookup variable is a scalar source, in scope ONLY as the root of an ``hours(...)``
    argument in a WHERE temporal offset. Everywhere else it is refused naming the
    variable, because a silent fall-through would read as a join the language does not
    have. Checks that need the schema or the supplied inputs (types, row count, a use
    that folds away at parameter resolution) live in the executor.
    """
    lookups = ast.lookup_clauses
    leaves = list(_predicate_leaves(ast.where_clause.predicate if ast.where_clause else None))
    for nec in ast.not_exists_clauses:
        if nec.where_clause is not None:
            leaves.extend(_predicate_leaves(nec.where_clause.predicate))
    temporal = [leaf for leaf in leaves if isinstance(leaf, TemporalComparison)]

    names = [lc.variable for lc in lookups]
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise GryphonParseError(f"LOOKUP variable '{name}' is declared more than once.")
        seen.add(name)
    clash = seen & _match_variables(ast)
    if clash:
        raise GryphonParseError(
            f"LOOKUP variable '{sorted(clash)[0]}' is also bound by a MATCH. A lookup variable is a scalar "
            "source and must have its own name."
        )

    def refuse(name: str, where: str) -> None:
        raise GryphonParseError(
            f"LOOKUP variable '{name}' cannot be used in {where}. It is in scope only inside "
            "hours(...) in a WHERE temporal comparison, e.g. WHERE t.data.opened_at + hours("
            f"{name}.data.<field>) < now()."
        )

    for leaf in leaves:
        if isinstance(leaf, TemporalComparison):
            if leaf.offset.base.variable in seen:
                refuse(leaf.offset.base.variable, "the base of a temporal offset")
            hours = leaf.offset.hours
            if isinstance(hours, FieldPath) and hours.variable not in seen:
                raise GryphonParseError(
                    f"hours({hours.variable}...) must read a field of a LOOKUP variable; "
                    f"'{hours.variable}' is not one. Declare it with LOOKUP {hours.variable} = (:label {{key: value}})."
                )
        elif hasattr(leaf, "field_path") and leaf.field_path.variable in seen:
            refuse(leaf.field_path.variable, "a WHERE comparison")
    for item in ast.return_clause.items or ():
        path = item.path if isinstance(item, ReturnItem) else item.aggregate.argument
        if path.variable in seen:
            refuse(path.variable, "RETURN")
    if ast.order_by is not None:
        for order_item in ast.order_by.items:
            if order_item.path.variable in seen:
                refuse(order_item.path.variable, "ORDER BY")

    used = {
        leaf.offset.hours.variable
        for leaf in temporal
        if isinstance(leaf, TemporalComparison) and isinstance(leaf.offset.hours, FieldPath)
    }
    for lc in lookups:
        if lc.variable not in used:
            raise GryphonParseError(
                f"LOOKUP variable '{lc.variable}' is declared but no temporal comparison reads it "
                f"(hours({lc.variable}.data.<field>)). An unused LOOKUP would silently select nothing."
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_gryphon(text: str | list[str]) -> GryphonAST:
    """Parse gryphon text into a GryphonAST.

    Args:
        text: A single string or a list of strings (one clause per line).
              Both forms are equivalent and normalize to the same AST.

    Returns:
        A frozen GryphonAST dataclass tree.

    Raises:
        GryphonParseError: If the text cannot be parsed.
    """
    if isinstance(text, list):
        normalized = " ".join(text)
    else:
        normalized = text.strip()

    try:
        tree = _PARSER.parse(normalized)
        return _TRANSFORMER.transform(tree)
    except GryphonParseError:
        raise
    except VisitError as exc:
        # lark wraps an exception raised inside a transformer rule; surface a
        # GryphonParseError raised by a rule (e.g. MIN(n)) as itself, so the message
        # the user sees is the rule's, not lark's "Error trying to process rule".
        if isinstance(exc.orig_exc, GryphonParseError):
            raise exc.orig_exc from None
        raise GryphonParseError(str(exc)) from exc
    except UnexpectedInput as exc:
        raise GryphonParseError(
            str(exc).split("\n")[0],
            line=getattr(exc, "line", None),
            col=getattr(exc, "column", None),
        ) from exc
    except Exception as exc:
        raise GryphonParseError(str(exc)) from exc
