"""Shared request logging, request IDs, and in-memory business metrics."""

from datetime import datetime, timezone
import json
import logging
import re
from threading import Lock
from time import perf_counter
from uuid import uuid4

from flask import g, jsonify, request


def valid_order(payload):
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("order_id"), str)
        and 0 < len(payload["order_id"].strip()) <= 100
        and type(payload.get("amount_cents")) is int
        and payload["amount_cents"] > 0
    )


def observe(app, service, business_path):
    logger = logging.getLogger(f"lab9.{service}")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.propagate = False
    lock = Lock()
    metrics = dict(success_count=0, failure_count=0, total_latency_ms=0.0,
                   last_latency_ms=0.0)

    def log(event, **fields):
        logger.info(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": service, "event": event, "request_id": g.request_id,
            "method": request.method, "path": request.path, **fields,
        }))

    @app.before_request
    def started():
        candidate = request.headers.get("X-Request-ID", "")
        g.request_id = (candidate if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", candidate)
                        else str(uuid4()))
        g.started = perf_counter()
        log("request_started")

    @app.after_request
    def completed(response):
        latency = (perf_counter() - g.started) * 1000
        success = response.status_code < 400
        # Probes, metrics reads, and delay controls do not dilute the error rate.
        if request.path == business_path and request.method == "POST":
            with lock:
                metrics["success_count" if success else "failure_count"] += 1
                metrics["total_latency_ms"] += latency
                metrics["last_latency_ms"] = latency
        body = response.get_json(silent=True)
        log("request_completed", status=response.status_code,
            outcome="success" if success else "failure", latency_ms=round(latency, 3),
            error=body.get("error") if isinstance(body, dict) else None)
        response.headers["X-Request-ID"] = g.request_id
        return response

    @app.get("/metrics")
    def get_metrics():
        with lock:
            snapshot = dict(metrics)
        count = snapshot["success_count"] + snapshot["failure_count"]
        return jsonify(
            service=service, request_count=count,
            success_count=snapshot["success_count"],
            failure_count=snapshot["failure_count"],
            error_rate=snapshot["failure_count"] / count if count else 0.0,
            average_latency_ms=round(snapshot["total_latency_ms"] / count, 3) if count else 0.0,
            last_latency_ms=round(snapshot["last_latency_ms"], 3),
        )
