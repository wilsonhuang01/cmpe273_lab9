"""Exercise running Checkout and Payment services over real HTTP."""

import argparse
import json
from time import monotonic, perf_counter, sleep
from uuid import uuid4

import requests


def require(condition, message):
    if not condition:
        raise RuntimeError(f"FAIL: {message}")


def run_scenarios(checkout_url, payment_url):
    with requests.Session() as session:
        session.trust_env = False

        def get(base, path):
            response = session.get(base + path, timeout=3)
            response.raise_for_status()
            return response.json()

        def delay(seconds):
            response = session.post(payment_url + "/admin/delay",
                                    json={"delay_seconds": seconds}, timeout=3)
            response.raise_for_status()

        def order(label, expected_status):
            request_id = f"lab9-{label}-{uuid4().hex[:12]}"
            started = perf_counter()
            response = session.post(
                checkout_url + "/v1/checkout",
                json={"order_id": request_id, "amount_cents": 1000},
                headers={"X-Request-ID": request_id}, timeout=timeout + 3,
            )
            elapsed = (perf_counter() - started) * 1000
            body = response.json()
            print(json.dumps(dict(scenario=label, request_id=request_id,
                                  status=response.status_code, latency_ms=round(elapsed, 3),
                                  response=body)), flush=True)
            require(response.status_code == expected_status, f"unexpected {label} response")
            require(response.headers.get("X-Request-ID") == body.get("request_id") == request_id,
                    "request ID was not preserved")
            return elapsed, body

        timeout = get(checkout_url, "/health")["payment_timeout_seconds"]
        get(payment_url, "/health")
        delay(0)
        print("=== 1. Successful Checkout -> Payment ===", flush=True)
        order("success", 201)
        baseline = get(checkout_url, "/metrics")
        payment_before = get(payment_url, "/metrics")["request_count"]

        try:
            print("=== 2. Payment delay exceeds Checkout timeout ===", flush=True)
            delay(timeout + 1)
            failed_latency, body = order("timeout", 504)
            require(body.get("error") == "payment_timeout", "Checkout did not detect timeout")
            require(get(checkout_url, "/health")["status"] == "ok", "Checkout stopped")
            require(get(payment_url, "/health")["status"] == "ok", "Payment stopped")
            failed = get(checkout_url, "/metrics")
            require(failed["failure_count"] == baseline["failure_count"] + 1,
                    "timeout was not counted")
            print(json.dumps({"phase": "failure", "checkout_metrics": failed}), flush=True)
        finally:
            delay(0)

        # A client timeout does not cancel Payment's in-flight request. Wait for
        # its completion so its slow log and metric remain visible in this phase.
        deadline = monotonic() + timeout + 4
        while get(payment_url, "/metrics")["request_count"] < payment_before + 1:
            require(monotonic() < deadline, "delayed Payment request did not finish")
            sleep(0.05)
        print(json.dumps({"phase": "after_delay", "payment_metrics": get(payment_url, "/metrics")}),
              flush=True)

        print("=== 3. Recovery: Payment delay removed ===", flush=True)
        recovered_latencies = [order(f"recovery-{i}", 201)[0] for i in range(1, 4)]
        recovered = get(checkout_url, "/metrics")
        require(recovered["error_rate"] < failed["error_rate"], "error rate did not decrease")
        require(max(recovered_latencies) < failed_latency, "latency did not recover")
        print(json.dumps({"phase": "recovery", "checkout_metrics": recovered}), flush=True)
        print("PASS: success, timeout detection, continued service, and recovery verified", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout-url", default="http://127.0.0.1:5000")
    parser.add_argument("--payment-url", default="http://127.0.0.1:5001")
    args = parser.parse_args()
    run_scenarios(args.checkout_url.rstrip("/"), args.payment_url.rstrip("/"))
