"""Langfuse tracing for the claim pipeline.

One trace per claim (`process-claim`), with the trace id derived from the
claim's `request_id`, so a transaction row maps to its trace without a lookup.
Each step is a typed observation under it: the Prompt Guard is a `guardrail`,
retrieval a `retriever` with an `embedding` child, each judge an `evaluator`,
the refund a `tool`. The LLM calls themselves are recorded as `generation`s
(model, tokens, cost) by the Langfuse LangChain callback, passed through
`langchain_config()`.

Tracing is observability, never a dependency of the pipeline:
- it is off unless both Langfuse keys are set (tests and local mock runs send
  nothing);
- if Langfuse fails to start an observation or record an update, the step
  runs untraced instead of failing;
- application errors still propagate unchanged, after being marked on the
  observation as level ERROR.

Spans are exported in a background thread by the SDK, so tracing adds no
network latency to a claim. `shutdown_tracing()` flushes what is pending when
the worker stops.
"""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any, Literal

import structlog
from langchain_core.runnables import RunnableConfig
from langfuse import Langfuse, propagate_attributes
from opentelemetry.sdk.trace.export import SpanExporter

from src.core.config import Settings, settings
from src.core.trace_masking import mask_otel_spans, pseudonymize_user_id

logger = structlog.get_logger(__name__)

ObservationType = Literal[
    "span", "chain", "retriever", "embedding", "evaluator", "guardrail", "tool", "agent"
]

CLAIM_TRACE_NAME = "process-claim"


class TraceObservation:
    """A Langfuse observation whose updates can never raise.

    Wraps None when tracing is off, so callers update it unconditionally.
    """

    def __init__(self, observation: Any = None) -> None:  # Any: one of the SDK's 9 observation classes
        self._observation = observation

    def update(
        self,
        *,
        output: Any = None,  # Any: whatever the step produced, serialized by the SDK
        metadata: dict[str, Any] | None = None,
        usage_details: dict[str, int] | None = None,
        level: Literal["DEBUG", "DEFAULT", "WARNING", "ERROR"] | None = None,
        status_message: str | None = None,
    ) -> None:
        """Record fields on the observation; a failure is logged, not raised."""
        if self._observation is None:
            return
        fields: dict[str, Any] = {
            "output": output,
            "metadata": metadata,
            "usage_details": usage_details,
            "level": level,
            "status_message": status_message,
        }
        try:
            self._observation.update(**{k: v for k, v in fields.items() if v is not None})
        except Exception as exc:  # noqa: BLE001 -- tracing must never break a claim; logged
            logger.warning("langfuse_update_failed", error=str(exc))


_NOOP = TraceObservation()
_UNSET = object()
_client: Any = _UNSET  # Any: Langfuse | None once resolved, _UNSET before
_public_key: str | None = None


def is_tracing_enabled(cfg: Settings = settings) -> bool:
    """True when tracing is switched on and both Langfuse keys are present."""
    return bool(cfg.LANGFUSE_TRACING_ENABLED and cfg.LANGFUSE_PUBLIC_KEY and cfg.LANGFUSE_SECRET_KEY)


def build_client(cfg: Settings = settings, *, span_exporter: SpanExporter | None = None) -> Langfuse:
    """Build a Langfuse client from settings, with masking applied at export.

    `span_exporter` replaces the network exporter (tests use an in-memory one).
    """
    return Langfuse(
        public_key=cfg.LANGFUSE_PUBLIC_KEY,
        secret_key=cfg.LANGFUSE_SECRET_KEY,
        base_url=cfg.LANGFUSE_BASE_URL or None,
        environment=cfg.LANGFUSE_TRACING_ENVIRONMENT,
        mask_otel_spans=mask_otel_spans,
        span_exporter=span_exporter,
    )


def configure_tracing(client: Langfuse | None, *, public_key: str | None = None) -> None:
    """Install `client` (None disables tracing) instead of building one lazily.

    `public_key` must be the client's own key: the LangChain callback finds
    its client by it.
    """
    global _client, _public_key
    _client = client
    _public_key = public_key if client is not None else None


def _get_client() -> Langfuse | None:
    """Return the active client, building it from settings on first use."""
    global _client, _public_key
    if _client is _UNSET:
        _client, _public_key = None, None
        if is_tracing_enabled():
            try:
                _client, _public_key = build_client(), settings.LANGFUSE_PUBLIC_KEY
                logger.info("langfuse_tracing_enabled", environment=settings.LANGFUSE_TRACING_ENVIRONMENT)
            except Exception as exc:  # noqa: BLE001 -- run untraced rather than not at all; logged
                logger.warning("langfuse_init_failed", error=str(exc))
    return _client if isinstance(_client, Langfuse) or _client is None else None


def _mark_error(observation: TraceObservation, exc: BaseException) -> None:
    observation.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")


@contextmanager
def observe(
    name: str,
    *,
    as_type: ObservationType,
    input: Any = None,  # Any: whatever the step consumes, serialized by the SDK
    metadata: dict[str, Any] | None = None,
    model: str | None = None,
) -> Iterator[TraceObservation]:
    """Record the enclosed block as a child observation of the current one."""
    client = _get_client()
    if client is None:
        yield _NOOP
        return
    # Any: the SDK overloads this method per literal as_type, so a variable
    # as_type matches no single overload under mypy.
    start: Any = client.start_as_current_observation
    stack = ExitStack()
    try:
        observation = TraceObservation(
            stack.enter_context(
                start(name=name, as_type=as_type, input=input, metadata=metadata, model=model)
            )
        )
    except Exception as exc:  # noqa: BLE001 -- run the step untraced; logged
        stack.close()
        logger.warning("langfuse_observation_failed", name=name, error=str(exc))
        yield _NOOP
        return
    with stack:
        try:
            yield observation
        except BaseException as exc:
            _mark_error(observation, exc)
            raise


@contextmanager
def claim_trace(
    request_id: str,
    *,
    user_id: str,
    input: Any,  # Any: the claim fields shown as the trace input
    tags: list[str] | None = None,
) -> Iterator[TraceObservation]:
    """Open the root `process-claim` trace for one claim.

    The trace id is derived from `request_id`, and the user id is a pseudonym.
    """
    client = _get_client()
    if client is None:
        yield _NOOP
        return
    stack = ExitStack()
    try:
        observation = TraceObservation(
            stack.enter_context(
                client.start_as_current_observation(
                    name=CLAIM_TRACE_NAME,
                    as_type="chain",
                    input=input,
                    trace_context={"trace_id": Langfuse.create_trace_id(seed=request_id)},
                )
            )
        )
        stack.enter_context(
            propagate_attributes(
                trace_name=CLAIM_TRACE_NAME,
                user_id=pseudonymize_user_id(user_id),
                metadata={"request_id": request_id},
                tags=tags,
            )
        )
    except Exception as exc:  # noqa: BLE001 -- process the claim untraced; logged
        stack.close()
        logger.warning("langfuse_trace_failed", request_id=request_id, error=str(exc))
        yield _NOOP
        return
    with stack:
        try:
            yield observation
        except BaseException as exc:
            _mark_error(observation, exc)
            raise


def langchain_config(run_name: str | None = None) -> RunnableConfig:
    """LangChain run config that records the call as a Langfuse generation.

    `run_name` names the generation after its action (e.g. `generate-verdict`)
    instead of the chat model's class. Empty when tracing is off. The callback
    nests under the current observation.
    """
    if _get_client() is None:
        return {}
    try:
        from langfuse.langchain import CallbackHandler

        config: RunnableConfig = {"callbacks": [CallbackHandler(public_key=_public_key)]}
        if run_name is not None:
            config["run_name"] = run_name
        return config
    except Exception as exc:  # noqa: BLE001 -- call the LLM untraced; logged
        logger.warning("langfuse_callback_failed", error=str(exc))
        return {}


def flush_tracing() -> None:
    """Export every pending span now (blocks until sent)."""
    client = _get_client()
    if client is not None:
        client.flush()


def shutdown_tracing() -> None:
    """Flush pending spans and stop the exporter; call once at process exit."""
    client = _get_client()
    if client is not None:
        try:
            client.shutdown()
        except Exception as exc:  # noqa: BLE001 -- exiting anyway; logged
            logger.warning("langfuse_shutdown_failed", error=str(exc))
