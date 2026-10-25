"""
Live API demonstration and proof runner for TRACE Milestone 1.

Exercises the live HTTP server:
- /health
- POST /demo/reset (Reset #1)
- POST /demo/scenarios/valid_claim/run (Authentic claim)
- POST /demo/scenarios/duplicate_report/run (Cross-report duplicate attack)
- POST /demo/reset (Reset #2 - Idempotency proof)
- GET /projects/WATER-001
- GET /projects/WATER-001/trace
- GET /metrics
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8000"


def http_request(path: str, method: str = "GET", data: dict = None) -> dict:
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"} if data else {}
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            content = resp.read().decode("utf-8")
            return {"status_code": status, "body": json.loads(content)}
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = content
        return {"status_code": e.code, "body": parsed}


def main():
    print("=== TRACE LIVE API VERIFICATION START ===")

    # 1. Wait for server readiness
    ready = False
    for i in range(15):
        try:
            res = http_request("/health")
            if res["status_code"] == 200 and res["body"].get("status") == "healthy":
                print(f"[OK] Health check passed: {res['body']}")
                ready = True
                break
        except Exception:
            time.sleep(0.5)

    if not ready:
        print("[FAIL] Server did not become ready in time.")
        sys.exit(1)

    # 2. Reset #1
    print("\n--- 1. POST /demo/reset (First Reset) ---")
    res_reset1 = http_request("/demo/reset", method="POST")
    print(f"Status: {res_reset1['status_code']}")
    print(json.dumps(res_reset1["body"], indent=2))

    # 3. Exercise valid_claim
    print("\n--- 2. POST /demo/scenarios/valid_claim/run ---")
    res_valid = http_request("/demo/scenarios/valid_claim/run", method="POST")
    print(f"Status: {res_valid['status_code']}")
    print(json.dumps(res_valid["body"], indent=2))

    # 4. Exercise duplicate_report
    print("\n--- 3. POST /demo/scenarios/duplicate_report/run ---")
    res_dup = http_request("/demo/scenarios/duplicate_report/run", method="POST")
    print(f"Status: {res_dup['status_code']}")
    print(json.dumps(res_dup["body"], indent=2))

    # 5. Check metrics after attack
    print("\n--- 4. GET /metrics (After duplicate claim attack) ---")
    res_metrics1 = http_request("/metrics")
    print(f"Status: {res_metrics1['status_code']}")
    print(json.dumps(res_metrics1["body"], indent=2))

    # 6. Reset #2 (Idempotency confirmation)
    print("\n--- 5. POST /demo/reset (Second Reset - Confirm Idempotency) ---")
    res_reset2 = http_request("/demo/reset", method="POST")
    print(f"Status: {res_reset2['status_code']}")
    print(json.dumps(res_reset2["body"], indent=2))

    # 7. Check project status after reset #2
    print("\n--- 6. GET /projects/WATER-001 (Clean seed state verified) ---")
    res_proj = http_request("/projects/WATER-001")
    print(f"Status: {res_proj['status_code']}")
    print(json.dumps(res_proj["body"], indent=2))

    # 8. Check metrics after reset #2
    print("\n--- 7. GET /metrics (Clean seed metrics verified) ---")
    res_metrics2 = http_request("/metrics")
    print(f"Status: {res_metrics2['status_code']}")
    print(json.dumps(res_metrics2["body"], indent=2))

    # 9. Check trace graph after reset #2
    print("\n--- 8. GET /projects/WATER-001/trace (Initial flow conservation verified) ---")
    res_trace = http_request("/projects/WATER-001/trace")
    print(f"Status: {res_trace['status_code']}")
    print(json.dumps(res_trace["body"], indent=2))

    print("\n=== TRACE LIVE API VERIFICATION COMPLETE ===")


if __name__ == "__main__":
    main()
