"""Deterministic tool registry.

The LLM only *selects* tools and proposes arguments. Everything else —
argument validation, hotel scoping, business rules, and database access —
happens here, in plain Python, where it can be tested and trusted.

Undeclared arguments that look like prices, totals, discounts, or
availability are rejected outright (the LLM cannot smuggle in a "price" or
"total" field) — prices and availability are computed by the backend, never
supplied by the model.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.services.booking_service import BookingError

logger = logging.getLogger(__name__)


# Hallucinated value fields: argument names through which an LLM might try
# to inject prices, totals, discounts, or availability into a tool call.
# Prices and availability are computed deterministically by the backend, so
# an *undeclared* argument with one of these names is rejected outright.
# Declared schema fields always take precedence (e.g. ``offered_price`` is a
# legitimate input to ``evaluate_price_offer``).
_HALLUCINATED_VALUE_FIELDS = {
    "price",
    "prices",
    "total",
    "total_price",
    "total_amount",
    "grand_total",
    "subtotal",
    "amount",
    "cost",
    "charge",
    "rate",
    "rates",
    "discount",
    "discounts",
    "discount_percent",
    "discounted_price",
    "availability",
    "available",
}


@dataclass
class ToolContext:
    """Who/what is invoking the tool."""

    hotel_id: int
    conversation_id: int | None = None
    guest_id: int | None = None
    channel: str = "web"
    actor_type: str = "agent"


@dataclass
class ToolExecutionResult:
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


# Handler signature: (db, ctx, args) -> JSON-serializable dict.
ToolHandler = Callable[[Session, ToolContext, BaseModel], dict[str, Any]]


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler
    read_only: bool = True


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def definitions(self) -> list[dict[str, Any]]:
        """Tool definitions in OpenAI function-calling format."""
        defs = []
        for spec in self._tools.values():
            schema = spec.args_model.model_json_schema()
            defs.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": schema,
                }
            )
        return defs

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        db: Session,
        ctx: ToolContext,
    ) -> ToolExecutionResult:
        """Validate arguments and run the tool. Never raises for tool errors."""
        spec = self._tools.get(name)
        if spec is None:
            return ToolExecutionResult(
                ok=False, error=f"Unknown tool: {name}. Available: {', '.join(self.names)}"
            )
        if not isinstance(arguments, dict):
            return ToolExecutionResult(ok=False, error="Tool arguments must be an object")

        # Reject hallucinated pricing/availability fields up front: the LLM must
        # never supply prices, totals, discounts, or availability as tool
        # arguments — those are computed deterministically by the backend.
        # (Declared schema fields such as EvaluateOfferArgs.offered_price are
        # legitimate inputs and always take precedence; only *undeclared*
        # lookalikes are rejected.)
        known_fields = set(spec.args_model.model_fields)
        hallucinated = sorted(
            k
            for k in arguments
            if k not in known_fields and k.lower() in _HALLUCINATED_VALUE_FIELDS
        )
        if hallucinated:
            logger.warning(
                "Tool %s rejected: hallucinated argument(s) %s",
                name,
                ", ".join(hallucinated),
            )
            return ToolExecutionResult(
                ok=False,
                error=(
                    f"Invalid argument(s) for {name}: {', '.join(hallucinated)}. "
                    "Prices, totals, discounts, and availability are computed by "
                    "the backend — never pass them as tool arguments. Call the "
                    "pricing/availability tools and use their results."
                ),
            )

        try:
            args = spec.args_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolExecutionResult(
                ok=False,
                error=f"Invalid arguments for {name}: {exc.errors(include_url=False)}",
            )

        # Tenant isolation: a tool may only act on the runner's hotel.
        args_hotel_id = getattr(args, "hotel_id", None)
        if args_hotel_id is not None and args_hotel_id != ctx.hotel_id:
            logger.warning(
                "Tool %s rejected: hotel_id %s does not match context hotel %s",
                name,
                args_hotel_id,
                ctx.hotel_id,
            )
            return ToolExecutionResult(
                ok=False,
                error=(
                    f"hotel_id {args_hotel_id} does not belong to this conversation "
                    f"(hotel {ctx.hotel_id})"
                ),
            )

        try:
            data = spec.handler(db, ctx, args)
        except BookingError as exc:
            logger.info("Tool %s rejected: %s", name, exc.detail)
            return ToolExecutionResult(ok=False, error=exc.detail)
        except ValueError as exc:
            logger.info("Tool %s validation failed: %s", name, exc)
            return ToolExecutionResult(ok=False, error=str(exc))
        except Exception:  # noqa: BLE001 - never leak internals to the LLM
            logger.exception("Tool %s failed unexpectedly", name)
            return ToolExecutionResult(
                ok=False,
                error="The tool failed due to an internal error. Please try again.",
            )
        return ToolExecutionResult(ok=True, data=_jsonable(data))


def build_registry() -> ToolRegistry:
    """Build the full registry. Import is deferred to avoid circulars."""
    from app.agent.tools import booking_tools, hotel_tools, knowledge_tools, ops_tools

    registry = ToolRegistry()
    for spec in hotel_tools.SPECS + booking_tools.SPECS + ops_tools.SPECS + knowledge_tools.SPECS:
        registry.register(spec)
    return registry
