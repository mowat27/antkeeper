"""Introspect an antkeeper handlers module into steps and workflows.

Every registered handler becomes a workflow. A handler that calls
``run_workflow`` is a composite workflow whose steps are resolved statically
from its source; any other registered handler is a single-step workflow.
Each step is described in markdown so an agent can perform it without the
antkeeper runtime.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from antkeeper.handlers.claude_code.factories import cc_handler
from antkeeper.handlers.ralph import _bash_validator, ralph

# Every handler built by a factory shares its factory's code object, which
# identifies the factory without relying on names or labels.
_CC_CODE = getattr(cc_handler("/noop"), "__code__")
_RALPH_CODE = getattr(ralph(cc_handler("/noop"), validator="noop"), "__code__")
_BASH_VALIDATOR_CODE = getattr(_bash_validator("noop"), "__code__")

# AST node types allowed in a ``run_workflow`` steps expression, e.g.
# ``[specify, implement]``, ``SDLC_STEPS`` or ``SDLC_STEPS[0:2]``.
_STEPS_EXPR_NODES = (
    ast.Expression, ast.Name, ast.Load, ast.List, ast.Tuple, ast.Subscript,
    ast.Slice, ast.Constant, ast.BinOp, ast.Add, ast.UnaryOp, ast.USub,
)

# Names used by the generated rig itself: the orchestrator agent directory and
# the closing workflow step it owns.
RESERVED_NAMES = frozenset({"orchestrator", "close"})

_MAX_HELPER_DEPTH = 2


class GenerationError(Exception):
    """Raised when a handlers file cannot be translated into a rig."""


class UnresolvableWorkflow(GenerationError):
    """Raised when one workflow's steps cannot be determined statically."""


@dataclass(frozen=True)
class Step:
    """One antkeeper step, performed by one rig seat.

    Attributes:
        name: The antkeeper step name.
        seat: Rig member id for the seat that performs the step.
        summary: One-line description of the step.
        instructions: Markdown describing how to perform the step.
        model: Model override declared by the step, if any.
        command: Slash command the step runs, if it is a ``cc_handler`` with
            a slash-command prompt.
    """

    name: str
    seat: str
    summary: str
    instructions: str
    model: str | None = None
    command: str | None = None


@dataclass(frozen=True)
class Workflow:
    """A registered antkeeper handler, expressed as an ordered list of steps.

    Attributes:
        name: Registered handler name.
        summary: One-line description of the workflow.
        doc: Full docstring of the handler.
        steps: Step names in execution order.
        composite: ``True`` when the handler composes steps with
            ``run_workflow``; ``False`` for a single-step workflow.
        glue_source: Handler source when it contains logic beyond running its
            steps (e.g. worktree setup), otherwise ``None``.
    """

    name: str
    summary: str
    doc: str
    steps: tuple[str, ...]
    composite: bool
    glue_source: str | None = None


@dataclass(frozen=True)
class HandlersSpec:
    """Steps and workflows extracted from a handlers module.

    Attributes:
        steps: Steps keyed by step name, in first-use order.
        workflows: Workflows keyed by registered handler name.
        skipped: Reasons keyed by handler name, for handlers whose steps could
            not be resolved statically.
    """

    steps: dict[str, Step]
    workflows: dict[str, Workflow]
    skipped: dict[str, str]


def introspect(module: ModuleType) -> HandlersSpec:
    """Extract steps and workflows from a loaded handlers module.

    Args:
        module: A module exposing an antkeeper ``app``.

    Returns:
        The steps and workflows defined by the module.

    Raises:
        GenerationError: If the module has no app or handlers, no workflow's
            steps can be resolved, or step names collide.
    """
    app = getattr(module, "app", None)
    handlers: dict[str, Callable] = getattr(app, "handlers", None) or {}
    if not handlers:
        raise GenerationError("handlers file defines no 'app' with registered handlers")
    return _Introspector(module, handlers).run()


def seat_id(name: str) -> str:
    """Convert a step name into a valid rig member id.

    Args:
        name: Antkeeper step name.

    Returns:
        The name with characters other than letters, digits, ``_`` and ``-``
        replaced by ``-``.
    """
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")


class _Introspector:
    """Walks a handlers module, naming and describing every step it uses."""

    def __init__(self, module: ModuleType, handlers: dict[str, Callable]) -> None:
        self.module = module
        self.handlers = handlers
        self.names = self._step_names()

    def run(self) -> HandlersSpec:
        """Build the HandlersSpec for the module."""
        steps: dict[str, Step] = {}
        workflows: dict[str, Workflow] = {}
        skipped: dict[str, str] = {}
        for name, handler in self.handlers.items():
            try:
                sequence = self._composition(handler, (name,))
            except UnresolvableWorkflow as error:
                skipped[name] = str(error)
                continue
            composite = sequence is not None
            step_names = []
            for fn in sequence if sequence is not None else [handler]:
                step_name = self._name_of(fn)
                if step_name not in steps:
                    steps[step_name] = self._step(step_name, fn)
                step_names.append(step_name)
            doc = _prose(inspect.getdoc(inspect.unwrap(handler)) or "")
            workflows[name] = Workflow(
                name=name,
                summary=_first_line(doc) or f"Run the antkeeper `{name}` handler.",
                doc=doc,
                steps=tuple(step_names),
                composite=composite,
                glue_source=self._glue_source(handler) if composite else None,
            )
        if not workflows:
            raise GenerationError("no workflow could be translated: " + "; ".join(skipped.values()))
        self._check_seats(steps)
        return HandlersSpec(steps=steps, workflows=workflows, skipped=skipped)

    # -- naming ---------------------------------------------------------------

    def _step_names(self) -> dict[Callable, str]:
        """Map step callables to names: registry keys, then public, then private globals."""
        names: dict[Callable, str] = {}
        for name, fn in self.handlers.items():
            names.setdefault(fn, name)
        members = [(k, v) for k, v in vars(self.module).items() if callable(v) and not k.startswith("__")]
        for key, value in sorted(members, key=lambda kv: kv[0].startswith("_")):
            try:
                names.setdefault(value, key)
            except TypeError:  # unhashable callable
                continue
        return names

    def _name_of(self, fn: Callable) -> str:
        """Return the antkeeper step name of a callable."""
        return self.names.get(fn) or getattr(fn, "__name__", repr(fn))

    def _check_seats(self, steps: dict[str, Step]) -> None:
        """Reject step names that are empty, reserved or collide once converted to seat ids."""
        seen: dict[str, str] = {}
        for step in steps.values():
            if not step.seat:
                raise GenerationError(f"step {step.name!r} has no usable seat name")
            if step.seat in RESERVED_NAMES:
                raise GenerationError(f"step name {step.name!r} is reserved by the generated rig; rename it")
            if step.seat in seen:
                raise GenerationError(f"steps {seen[step.seat]!r} and {step.name!r} both map to seat {step.seat!r}")
            seen[step.seat] = step.name

    # -- composition ----------------------------------------------------------

    def _composition(self, handler: Callable, stack: tuple[str, ...]) -> list[Callable] | None:
        """Return the flattened step sequence of a composite handler, or ``None`` if atomic.

        Steps come from ``run_workflow`` calls and from direct ``step(runner, state)``
        calls in source order. A step that is itself a composite registered
        handler is expanded in place.
        """
        func = _function_node(handler)
        if func is None or not func.args.args:
            return None
        runner_arg = func.args.args[0].arg
        calls = sorted(
            (node for node in ast.walk(func) if isinstance(node, ast.Call)),
            key=lambda node: (node.lineno, node.col_offset),
        )
        sequence: list[Callable] = []
        composite = False
        for call in calls:
            if _callee_name(call) == "run_workflow":
                composite = True
                found = self._eval_steps(call, stack[-1])
            else:
                callee = self._direct_step(call, runner_arg)
                found = [callee] if callee is not None else []
            for fn in found:
                name = self._name_of(fn)
                if name in stack:
                    raise UnresolvableWorkflow(f"workflow {stack[0]!r} composes itself via {name!r}")
                nested = self._composition(fn, (*stack, name)) if name in self.handlers else None
                sequence.extend(nested if nested is not None else [fn])
        return sequence if composite else None

    def _eval_steps(self, call: ast.Call, workflow: str) -> list[Callable]:
        """Statically resolve the steps argument of a ``run_workflow`` call."""
        if len(call.args) >= 3:
            expr = call.args[2]
        else:
            expr = next((kw.value for kw in call.keywords if kw.arg == "steps"), None)
        if expr is None:
            raise UnresolvableWorkflow(f"workflow {workflow!r}: run_workflow call has no steps argument")
        tree = ast.Expression(body=expr)
        text = ast.unparse(expr)
        if not all(isinstance(node, _STEPS_EXPR_NODES) for node in ast.walk(tree)):
            raise UnresolvableWorkflow(f"workflow {workflow!r}: cannot statically resolve steps {text!r}")
        try:
            value = eval(compile(tree, "<steps>", "eval"), {**vars(self.module), "__builtins__": {}})
        except Exception as error:
            raise UnresolvableWorkflow(f"workflow {workflow!r}: cannot resolve steps {text!r}: {error}") from error
        if not isinstance(value, (list, tuple)) or not all(callable(fn) for fn in value):
            raise UnresolvableWorkflow(f"workflow {workflow!r}: steps {text!r} is not a list of handlers")
        return list(value)

    def _direct_step(self, call: ast.Call, runner_arg: str) -> Callable | None:
        """Return the module-level step invoked as ``step(runner, ...)``, if any."""
        if not isinstance(call.func, ast.Name) or not call.args:
            return None
        first = call.args[0]
        if not (isinstance(first, ast.Name) and first.id == runner_arg):
            return None
        value = vars(self.module).get(call.func.id)
        return value if callable(value) else None

    def _glue_source(self, handler: Callable) -> str | None:
        """Return the handler's source if it does more than ``return run_workflow(...)``."""
        func = _function_node(handler)
        if func is None:
            return None
        body = func.body[1:] if ast.get_docstring(func) is not None else func.body
        if (
            len(body) == 1
            and isinstance(body[0], ast.Return)
            and isinstance(body[0].value, ast.Call)
            and _callee_name(body[0].value) == "run_workflow"
        ):
            return None
        return _source(handler)

    # -- step descriptions ----------------------------------------------------

    def _step(self, name: str, fn: Callable) -> Step:
        """Describe one step."""
        target = inspect.unwrap(fn)
        nonlocals = _cc_nonlocals(target)
        if nonlocals is not None:
            command = str(nonlocals["command"])
            slash = command.split()[0] if command.startswith("/") else None
            return Step(
                name=name,
                seat=seat_id(name),
                summary=f"Runs `{_one_line(command)}`.",
                instructions=self._describe(target, depth=0, seen={target}),
                model=nonlocals.get("model"),
                command=slash,
            )
        doc = inspect.getdoc(target) or ""
        return Step(
            name=name,
            seat=seat_id(name),
            summary=_first_line(doc) or f"Runs the `{name}` step.",
            instructions=self._describe(target, depth=0, seen={target}),
        )

    def _describe(self, fn: Callable, *, depth: int, seen: set[Callable]) -> str:
        """Describe how to perform a callable, recursing into ralph wrappers and helpers."""
        target = inspect.unwrap(fn)
        nonlocals = _cc_nonlocals(target)
        if nonlocals is not None:
            return _describe_cc(nonlocals)
        if getattr(target, "__code__", None) is _RALPH_CODE:
            return self._describe_ralph(target, depth=depth, seen=seen)
        return self._describe_python(target, depth=depth, seen=seen)

    def _describe_ralph(self, fn: Callable, *, depth: int, seen: set[Callable]) -> str:
        """Describe a ralph retry-validation wrapper and the handler it wraps."""
        nonlocals = inspect.getclosurevars(fn).nonlocals
        attempts = int(nonlocals["max_retries"]) + 1
        validator = nonlocals["resolved_validator"]
        lines = [
            f"Repeat the attempt below until its validator passes, at most {attempts} attempts in total.",
            "After each attempt, run the validator against the updated state. When it fails, use its",
            "feedback to improve the next attempt. If every attempt fails, fail the step.",
            "",
        ]
        if getattr(validator, "__code__", None) is _BASH_VALIDATOR_CODE:
            script = inspect.getclosurevars(validator).nonlocals["script_path"]
            lines += [
                f"**Validator:** run `{script}` with the state as JSON on stdin. It prints",
                '`{"success": true|false, "feedback": "..."}`; a non-zero exit fails the step.',
            ]
        else:
            lines += ["**Validator** (passes when `success` is true):", "", _code_block(_source(validator))]
        learnings = nonlocals.get("learnings_file")
        if learnings:
            lines += [
                "",
                f"After each failed attempt, append the feedback to `{learnings}` (interpolate `$name` from state)",
                "under a heading naming the attempt.",
            ]
        inner = nonlocals["handler"]
        lines += ["", "**Each attempt:**", "", self._describe(inner, depth=depth, seen=seen | {inner})]
        return "\n".join(lines)

    def _describe_python(self, fn: Callable, *, depth: int, seen: set[Callable]) -> str:
        """Describe a hand-written handler by its docstring, source and module-level helpers."""
        doc = inspect.getdoc(fn)
        source = _source(fn)
        if source is None:
            return f"Perform `{getattr(fn, '__name__', fn)!r}`. {doc or 'No source is available.'}"
        lines = [
            "This step is hand-written Python. Perform its equivalent yourself: read inputs from",
            "workflow state, carry out its effects (commands, files, prompts), and merge the keys it",
            "returns into state. `runner.report_progress(...)` is a status note;",
            "`runner.fail(message)` means fail the step with that message.",
            "",
            _code_block(source),
        ]
        if depth >= _MAX_HELPER_DEPTH:
            return "\n".join(lines)
        for name, helper in self._helpers(fn, seen):
            lines += ["", f"**Helper `{name}`:**", "", self._describe(helper, depth=depth + 1, seen=seen | {helper})]
        return "\n".join(lines)

    def _helpers(self, fn: Callable, seen: set[Callable]) -> list[tuple[str, Callable]]:
        """Return module-level steps and functions that ``fn`` references, in name order."""
        func = _function_node(fn)
        if func is None:
            return []
        found: dict[str, Callable] = {}
        for node in ast.walk(func):
            if not isinstance(node, ast.Name) or node.id in found:
                continue
            value = vars(self.module).get(node.id)
            if not callable(value) or value in seen or isinstance(value, type):
                continue
            target = inspect.unwrap(value)
            code = getattr(target, "__code__", None)
            local = getattr(target, "__module__", None) == self.module.__name__
            if code is _CC_CODE or code is _RALPH_CODE or local:
                found[node.id] = value
        return sorted(found.items())


def _describe_cc(nonlocals: dict[str, Any]) -> str:
    """Describe a ``cc_handler`` step from its closure variables."""
    command = str(nonlocals["command"])
    state_updates = list(nonlocals.get("state_updates") or [])
    lines = [
        "Run this Claude Code prompt in your own session:",
        "",
        _code_block(command, "text"),
        "",
        "Replace each `$name` placeholder with the value of `name` from workflow state; fail the",
        "step if a placeholder has no value.",
    ]
    if command.startswith("/"):
        lines += [
            f"The prompt is a slash command: invoke `{command.split()[0]}` (for example with your Skill tool),",
            "passing the rest of the line as its arguments, and follow it to completion.",
        ]
    lines.append("")
    if state_updates:
        fields = ", ".join(f"`{name}`" for name in state_updates)
        lines.append(f"Then take these fields from the outcome and merge them into state: {fields}.")
        lines.append("If you cannot determine a field, fail the step rather than guessing.")
    else:
        lines.append("This step does not add anything to workflow state.")
    opts = nonlocals.get("opts")
    if opts:
        lines += ["", f"Antkeeper passed these Claude CLI options to the step: `{' '.join(map(str, opts))}`. Honour their intent."]
    env = nonlocals.get("env")
    if env:
        names = ", ".join(f"`{name}`" for name in env)
        lines += ["", f"Antkeeper sets these environment variables for the step (see the handlers file): {names}."]
    return "\n".join(lines)


def _cc_nonlocals(fn: Callable) -> dict[str, Any] | None:
    """Return the closure variables of a ``cc_handler`` handler, or ``None`` for other callables."""
    if getattr(fn, "__code__", None) is not _CC_CODE:
        return None
    return dict(inspect.getclosurevars(fn).nonlocals)


def _function_node(fn: Callable) -> ast.FunctionDef | None:
    """Parse a callable's source into its function definition node."""
    source = _source(fn)
    if source is None:
        return None
    try:
        node = ast.parse(source).body[0]
    except (SyntaxError, IndexError):
        return None
    return node if isinstance(node, ast.FunctionDef) else None


def _source(fn: Callable) -> str | None:
    """Return the dedented source of a callable, or ``None`` when unavailable."""
    try:
        return textwrap.dedent(inspect.getsource(inspect.unwrap(fn))).strip("\n")
    except (OSError, TypeError):
        return None


def _callee_name(call: ast.Call) -> str | None:
    """Return the simple name of a call's callee (``f(...)`` or ``mod.f(...)``)."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _code_block(text: str | None, lang: str = "python") -> str:
    """Wrap text in a fenced markdown code block."""
    return f"```{lang}\n{text or ''}\n```"


def _prose(doc: str) -> str:
    """Return a docstring without its ``Args:``/``Returns:``-style sections."""
    match = re.search(r"^(Args|Arguments|Returns|Raises|Yields|Examples?):\s*$", doc, flags=re.MULTILINE)
    return (doc[: match.start()] if match else doc).strip()


def _first_line(text: str) -> str:
    """Return the first non-empty line of text."""
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _one_line(text: str) -> str:
    """Collapse whitespace so text fits on one line."""
    return " ".join(text.split())
