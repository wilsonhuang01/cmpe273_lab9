"""Payment HTTP service with a controllable delay for the timeout experiment."""

import argparse
from threading import Lock
import time

from flask import Flask, g, jsonify, request

from common import observe, valid_order


def create_app():
    app = Flask(__name__)
    observe(app, "payment", "/v1/payments")
    delay_lock = Lock()
    delay_seconds = 0.0

    @app.get("/health")
    def health():
        return jsonify(service="payment", status="ok")

    @app.post("/admin/delay")
    def set_delay():
        nonlocal delay_seconds
        payload = request.get_json(silent=True)
        delay = payload.get("delay_seconds") if isinstance(payload, dict) else None
        if type(delay) not in (int, float) or not 0 <= delay <= 30:
            return jsonify(error="delay_seconds_must_be_between_0_and_30"), 400
        with delay_lock:
            delay_seconds = float(delay)
        return jsonify(delay_seconds=delay)

    @app.post("/v1/payments")
    def pay():
        payload = request.get_json(silent=True)
        if not valid_order(payload):
            return jsonify(error="invalid_order", request_id=g.request_id), 400
        with delay_lock:
            delay = delay_seconds
        time.sleep(delay)
        # Simulated payment only: no external charge or financial side effect.
        return jsonify(order_id=payload["order_id"], status="paid",
                       request_id=g.request_id), 200

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    create_app().run(host="127.0.0.1", port=args.port, threaded=True)
