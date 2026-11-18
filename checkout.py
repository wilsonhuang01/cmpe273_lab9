"""Checkout HTTP service: one bounded Payment call, with no automatic retries."""

import argparse
import math
import os

from flask import Flask, g, jsonify, request
import requests

from common import observe, valid_order


def create_app(payment_url="http://127.0.0.1:5001", payment_timeout=0.5):
    if not math.isfinite(payment_timeout) or not 0 < payment_timeout <= 5:
        raise ValueError("payment_timeout must be greater than 0 and at most 5 seconds")
    app = Flask(__name__)
    observe(app, "checkout", "/v1/checkout")

    @app.get("/health")
    def health():
        return jsonify(service="checkout", status="ok",
                       payment_timeout_seconds=payment_timeout)

    @app.post("/v1/checkout")
    def checkout():
        payload = request.get_json(silent=True)
        if not valid_order(payload):
            return jsonify(error="invalid_order", request_id=g.request_id), 400
        try:
            # Ignore proxy environment variables for this local service call.
            with requests.Session() as session:
                session.trust_env = False
                with session.post(
                    f"{payment_url.rstrip('/')}/v1/payments",
                    json={"order_id": payload["order_id"],
                          "amount_cents": payload["amount_cents"]},
                    headers={"X-Request-ID": g.request_id},
                    timeout=(payment_timeout, payment_timeout),
                    allow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        return jsonify(error="payment_bad_response", request_id=g.request_id), 502
                    payment = response.json()
                    if (not isinstance(payment, dict)
                        or payment.get("status") != "paid"
                        or payment.get("order_id") != payload["order_id"]
                        or payment.get("request_id") != g.request_id):
                        raise ValueError("invalid payment response")
        except requests.Timeout:
            return jsonify(error="payment_timeout", request_id=g.request_id), 504
        except ValueError:
            return jsonify(error="payment_bad_response", request_id=g.request_id), 502
        except requests.RequestException:
            return jsonify(error="payment_unavailable", request_id=g.request_id), 503
        return jsonify(order_id=payload["order_id"], status="completed",
                       request_id=g.request_id), 201

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    create_app(
        payment_url=os.environ.get("PAYMENT_URL", "http://127.0.0.1:5001"),
        payment_timeout=float(os.environ.get("PAYMENT_TIMEOUT_SECONDS", "0.5")),
    ).run(host="127.0.0.1", port=args.port, threaded=True)
