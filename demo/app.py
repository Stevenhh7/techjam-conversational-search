from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from solution.agent import Agent  # noqa: E402
from solution.config import SolutionConfig  # noqa: E402
from solution.llm.base import SemanticRanker  # noqa: E402
from solution.llm.disabled import DisabledSemanticRanker  # noqa: E402
from solution.llm.qwen import OllamaQwenSemanticRanker  # noqa: E402


CATALOG_PATH = REPOSITORY_ROOT / "data" / "catalog.jsonl"
INDEX_PATH = Path(__file__).resolve().parent / "_assets" / "webapp" / "index.html"
DEFAULT_SUMMARY_PATH = (
    REPOSITORY_ROOT / "experiments" / "analysis" / "context_programming_dev_summary.json"
)
QWEN_SUMMARY_PATH = (
    REPOSITORY_ROOT / "experiments" / "analysis" / "qwen_context_dev_ablation.json"
)
MAX_TURNS = 10
MAX_MESSAGE_CHARS = 2_000
MAX_BODY_BYTES = 64 * 1024
MAX_SESSIONS = 128
AGENT_TIMEOUT_SECONDS = 180.0

DEMO_SCENARIOS = (
    {
        "sample_id": "guided-browsing",
        "scenario_type": "Browsing → clarification",
        "label": "1 · Open browsing and proactive cutoff",
        "first_message": "Show me some ideas.",
        "profile": {},
    },
    {
        "sample_id": "guided-buying",
        "scenario_type": "Buying",
        "label": "2 · High-intent buying",
        "first_message": "I want a black waterproof hiking jacket under $150.",
        "profile": {},
    },
    {
        "sample_id": "guided-override",
        "scenario_type": "Intent Override",
        "label": "3 · Start broad, then override",
        "first_message": "I am exploring lightweight outdoor clothing.",
        "profile": {},
    },
    {
        "sample_id": "guided-boundary",
        "scenario_type": "Boundary",
        "label": "4 · No preference boundary",
        "first_message": "I need hiking shoes, but I have no color preference.",
        "profile": {},
    },
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def demo_config() -> SolutionConfig:
    """Return a bounded demo config; Qwen stays off unless explicitly enabled."""

    base = SolutionConfig()
    return replace(
        base,
        semantic_ranker_enabled=_env_bool("CONTEXTCART_LLM_ENABLED", False),
        semantic_ranker_backend=os.getenv("CONTEXTCART_LLM_BACKEND", "ollama").strip()
        or "disabled",
        semantic_ranker_model=os.getenv("CONTEXTCART_LLM_MODEL", base.semantic_ranker_model).strip()
        or base.semantic_ranker_model,
        semantic_ranker_base_url=os.getenv(
            "CONTEXTCART_LLM_BASE_URL", base.semantic_ranker_base_url
        ).strip(),
        semantic_ranker_timeout_ms=_bounded_float(
            "CONTEXTCART_LLM_TIMEOUT_MS", 15_000.0, 1_000.0, 120_000.0
        ),
        semantic_ranker_top_n=_bounded_int("CONTEXTCART_LLM_TOP_N", 15, 1, 30),
    )


def build_ranker(config: SolutionConfig, enabled: bool) -> SemanticRanker:
    if not enabled or config.semantic_ranker_backend in {"", "disabled"}:
        return DisabledSemanticRanker(config.semantic_ranker_model, "disabled from demo page")
    return OllamaQwenSemanticRanker(
        config.semantic_ranker_model,
        config.semantic_ranker_base_url,
        config.semantic_ranker_timeout_ms,
        config.semantic_ranker_keep_alive,
        config.semantic_ranker_temperature,
        config.semantic_ranker_num_ctx,
        config.semantic_ranker_num_predict,
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def verified_evidence() -> dict[str, Any]:
    """Load tracked aggregate evidence without touching labels at demo runtime."""

    default = _read_json(DEFAULT_SUMMARY_PATH)
    qwen = _read_json(QWEN_SUMMARY_PATH)
    metrics = dict(default.get("metrics") or {})
    return {
        "source": "tracked dev150 summaries",
        "sample_count": default.get("sample_count", 150),
        "dataset_sha256": default.get("dataset_sha256"),
        "catalog_sha256": default.get("catalog_sha256"),
        "metrics": {
            "hit_rate_at_10": metrics.get("hit_rate_at_10"),
            "mrr": metrics.get("mrr"),
            "mttc": metrics.get("mttc"),
            "efficiency": metrics.get("efficiency"),
            "technical_score": metrics.get("recommended_technical_score"),
        },
        "duration_s": metrics.get("elapsed_seconds"),
        "scenario_metrics": metrics.get("scenario_metrics", {}),
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "qwen": {
            "decision": qwen.get("decision"),
            "baseline": qwen.get("baseline", {}),
            "candidate": qwen.get("candidate", {}),
            "delta": qwen.get("delta", {}),
            "ollama": qwen.get("ollama", {}),
            "gate": qwen.get("gate", {}),
        },
    }


class DemoApp:
    """Thread-safe local API around the real Agent.

    BM25 owns a SQLite connection, so construction and every Agent mutation are
    serialized on the same worker thread.
    """

    def __init__(self, catalog_path: Path = CATALOG_PATH) -> None:
        self.catalog_path = catalog_path
        self.config = demo_config()
        self._jobs: queue.Queue[
            tuple[Callable[[], Any], queue.Queue[tuple[str, Any]]] | None
        ] = queue.Queue(maxsize=32)
        self._state_lock = threading.Lock()
        self._ready = False
        self._boot_error: str | None = None
        self.agent: Agent | None = None
        self._sessions: dict[str, dict[str, Any]] = {}
        self._turns: dict[str, int] = {}
        self._worker = threading.Thread(
            target=self._run,
            daemon=True,
            name="contextcart-agent",
        )
        self._worker.start()

    def _run(self) -> None:
        try:
            agent = Agent(self.catalog_path, config=self.config, diagnostics=True)
            with self._state_lock:
                self.agent = agent
                self._ready = True
        except Exception as exc:  # surface boot failures through /api/status
            with self._state_lock:
                self._boot_error = f"{type(exc).__name__}: {exc}"
            return

        while True:
            job = self._jobs.get()
            if job is None:
                return
            function, result_queue = job
            try:
                result_queue.put(("ok", function()))
            except Exception as exc:
                result_queue.put(("error", exc))

    def _call(self, function: Callable[[], Any]) -> Any:
        if not self._ready:
            raise RuntimeError(self._boot_error or "agent is still booting")
        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
        try:
            self._jobs.put((function, result_queue), timeout=2.0)
            kind, value = result_queue.get(timeout=AGENT_TIMEOUT_SECONDS)
        except queue.Full as exc:
            raise RuntimeError("demo request queue is full") from exc
        except queue.Empty as exc:
            raise TimeoutError("agent did not respond within the demo timeout") from exc
        if kind == "error":
            raise value
        return value

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            if not self._ready:
                return {"ready": False, "boot_error": self._boot_error}
            agent = self.agent
        assert agent is not None
        llm = agent.semantic_ranker.status()
        return {
            "ready": True,
            "model": self.config.semantic_ranker_model,
            "backend": self.config.semantic_ranker_backend,
            "llm_enabled": bool(llm.get("enabled")),
            "llm": llm,
            "catalog_size": len(agent.products),
            "dense": {
                "enabled": agent.dense.enabled,
                "backend": getattr(agent.dense, "backend", None),
                "reason": agent.dense.reason,
            },
            "sessions": len(self._sessions),
        }

    @staticmethod
    def scenarios() -> list[dict[str, Any]]:
        return [dict(item) for item in DEMO_SCENARIOS]

    def set_llm(self, enabled: bool) -> dict[str, Any]:
        self._call(lambda: self._set_llm_impl(enabled))
        return self.status()

    def _set_llm_impl(self, enabled: bool) -> None:
        assert self.agent is not None
        previous = self.agent.semantic_ranker
        self.agent.semantic_ranker = build_ranker(self.config, enabled)
        self.agent.semantic_ranker_explicit = enabled
        close = getattr(previous, "close", None)
        if callable(close):
            close()

    def reset(self, scenario: dict[str, Any] | None) -> dict[str, Any]:
        return self._call(lambda: self._reset_impl(scenario or {}))

    def _reset_impl(self, scenario: dict[str, Any]) -> dict[str, Any]:
        assert self.agent is not None
        if len(self._sessions) >= MAX_SESSIONS:
            oldest = next(iter(self._sessions))
            self._drop_session(oldest)
        session_id = f"web-{uuid.uuid4().hex[:12]}"
        profile = scenario.get("profile") if isinstance(scenario.get("profile"), dict) else {}
        self.agent.reset(session_id, profile)
        meta = {
            "session_id": session_id,
            "sample_id": str(scenario.get("sample_id") or "free-chat")[:80],
            "scenario_type": str(scenario.get("scenario_type") or "Free chat")[:80],
            "label": str(scenario.get("label") or "Free chat")[:120],
            "first_message": str(scenario.get("first_message") or "")[:MAX_MESSAGE_CHARS],
        }
        self._sessions[session_id] = meta
        self._turns[session_id] = 0
        return dict(meta)

    def _drop_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._turns.pop(session_id, None)
        if self.agent is not None:
            self.agent.sessions.pop(session_id, None)
            self.agent.traces.pop(session_id, None)
            self.agent.response_cache.pop(session_id, None)
            self.agent.profile_snapshots.pop(session_id, None)

    def respond(self, session_id: str, message: str) -> dict[str, Any]:
        return self._call(lambda: self._respond_impl(session_id, message))

    def _respond_impl(self, session_id: str, message: str) -> dict[str, Any]:
        assert self.agent is not None
        meta = self._sessions.get(session_id)
        if meta is None:
            raise KeyError("session not found; start a new session")
        turn = self._turns[session_id] + 1
        if turn > MAX_TURNS:
            raise ValueError("the competition limit is 10 turns; start a new session")
        clean_message = message.strip()
        if not clean_message:
            raise ValueError("message is required")
        if len(clean_message) > MAX_MESSAGE_CHARS:
            raise ValueError(f"message exceeds {MAX_MESSAGE_CHARS} characters")

        before = self.agent.semantic_ranker.status()
        response = self.agent.respond(session_id, clean_message, turn, top_k=10)
        trace = self.agent.get_trace(session_id)[-1]
        after = dict(self.agent.semantic_ranker.status())
        after["this_call_attempted"] = int(after.get("request_count") or 0) > int(
            before.get("request_count") or 0
        )
        after["this_call_succeeded"] = int(after.get("success_count") or 0) > int(
            before.get("success_count") or 0
        )
        self._turns[session_id] = turn

        recommendations = []
        for item in response.get("recommendations") or []:
            if not isinstance(item, dict):
                continue
            parent_asin = str(item.get("parent_asin") or "")
            if parent_asin in self.agent.products:
                recommendations.append(self._product_card(parent_asin))
            if len(recommendations) >= 10:
                break
        return {
            "turn": turn,
            "message": str(response.get("message") or ""),
            "ask_attribute": response.get("ask_attribute"),
            "recommendations": recommendations,
            "prediction": self._prediction(trace, after),
            "usage": response.get("usage") or {},
            "session": dict(meta),
        }

    def _product_card(self, parent_asin: str) -> dict[str, Any]:
        assert self.agent is not None
        product = self.agent.products[parent_asin]
        return {
            "parent_asin": parent_asin,
            "title": str(product.get("title") or "")[:180],
            "categories": [str(value) for value in (product.get("categories") or [])[-3:]],
            "price": product.get("price"),
            "rating": product.get("average_rating"),
        }

    @staticmethod
    def _prediction(trace: dict[str, Any], llm_status: dict[str, Any]) -> dict[str, Any]:
        routing = trace.get("routing") or {}
        state = trace.get("state") or {}
        clarification = trace.get("clarification") or {}
        ranker = {**(trace.get("semantic_ranker") or {}), **llm_status}
        return {
            "intent": trace.get("intent"),
            "buying_probability": trace.get("buying_probability"),
            "routing": routing,
            "state": state,
            "distilled_context": trace.get("distilled_context") or {},
            "context_program": trace.get("context_program") or {},
            "strategy_outcome": trace.get("strategy_outcome") or {},
            "routes": {
                str(name): len(values) for name, values in (trace.get("routes") or {}).items()
            },
            "probe": trace.get("probe") or {},
            "over_generality": trace.get("over_generality") or {},
            "retrieval_cutoff": bool(trace.get("retrieval_cutoff")),
            "constraints": {
                "applied": trace.get("applied_constraints") or [],
                "relaxed": trace.get("relaxed_constraints") or [],
                "diversity": bool(trace.get("diversity_applied")),
            },
            "clarification": {
                **clarification,
                "attribute": trace.get("ask_attribute"),
            },
            "llm": {
                "enabled": ranker.get("enabled"),
                "backend": ranker.get("backend"),
                "applied": ranker.get("applied"),
                "reason": ranker.get("reason"),
                "attempted": ranker.get("this_call_attempted"),
                "succeeded": ranker.get("this_call_succeeded"),
                "last_error": ranker.get("last_error"),
                "last_latency_ms": ranker.get("last_latency_ms"),
                "request_count": ranker.get("request_count"),
                "success_count": ranker.get("success_count"),
                "fallback_count": ranker.get("fallback_count"),
            },
            "fused_count": len(trace.get("sparse_fused") or []),
            "final_count": len(trace.get("final") or []),
        }

    def close(self) -> None:
        if self._ready and self.agent is not None:
            try:
                self._call(self.agent.close)
            except Exception:
                pass
        try:
            self._jobs.put_nowait(None)
        except queue.Full:
            pass


class DemoHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: DemoApp) -> None:
        self.demo_app = app
        super().__init__(address, DemoHandler)


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "ContextCartDemo/1.0"

    @property
    def app(self) -> DemoApp:
        return self.server.demo_app  # type: ignore[attr-defined, no-any-return]

    def _headers(self, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; form-action 'none'",
        )

    def _json(self, code: int, value: object) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._headers("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self) -> None:
        if not INDEX_PATH.is_file():
            self._json(500, {"error": f"frontend asset missing: {INDEX_PATH}"})
            return
        body = INDEX_PATH.read_bytes()
        self.send_response(200)
        self._headers("text/html; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError(f"request body must be at most {MAX_BODY_BYTES} bytes")
        if length == 0:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be a JSON object") from exc
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {"/", "/index.html"}:
            self._html()
        elif path == "/api/status":
            self._json(200, self.app.status())
        elif path == "/api/scenarios":
            self._json(200, {"scenarios": self.app.scenarios()})
        elif path == "/api/evidence":
            self._json(200, verified_evidence())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        try:
            body = self._body()
            if not self.app.status().get("ready"):
                self._json(503, {"error": "agent is still booting", "status": self.app.status()})
                return
            if path == "/api/reset":
                scenario = body.get("scenario")
                self._json(200, self.app.reset(scenario if isinstance(scenario, dict) else None))
            elif path == "/api/respond":
                self._json(
                    200,
                    self.app.respond(
                        str(body.get("session_id") or ""),
                        str(body.get("message") or ""),
                    ),
                )
            elif path == "/api/llm":
                self._json(200, self.app.set_llm(bool(body.get("enabled"))))
            else:
                self._json(404, {"error": "not found"})
        except (KeyError, ValueError) as exc:
            self._json(400, {"error": str(exc)})
        except TimeoutError as exc:
            self._json(504, {"error": str(exc)})
        except Exception as exc:
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, format_string: str, *args: object) -> None:
        print("[demo]", format_string % args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the ContextCart local web demo.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=_bounded_int("CONTEXTCART_WEB_PORT", 7860, 1, 65_535),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = DemoApp()
    server = DemoHTTPServer((args.host, args.port), app)
    print(f"ContextCart local demo: http://{args.host}:{args.port}")
    print("Building the 50K in-memory catalog index; wait for the ready overlay to close.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ContextCart demo.")
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()
