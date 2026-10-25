"""
Live API demonstration and proof runner for TRACE Milestone 1.

Follows the explicit tranche demonstration sequence required by PS 4.2 evaluation:
1. Reset the project.
2. Display initial funding, current tranche, released amount, verified spend, and freeze state.
3. Attempt the first tranche release and show the real result (Tranche 1 released).
4. Submit a valid signed claim (Evidence cryptographically verified).
5. Attempt the next tranche release and show actual spending threshold and outcome (Blocked: Insufficient spend).
6. Trigger a qualifying security attack (Duplicate invoice reuse attack -> Project frozen).
7. Attempt release again and show that the freeze blocks it (Blocked: Project frozen).
8. Fetch and display the complete end-to-end fund trace:
   DONATION -> ALLOCATION -> SWAP -> BRIDGE -> OFFRAMP -> VENDOR_PAYMENT.
9. Verify system metrics and reset idempotency.
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

    # Step 1: Reset the project
    print("\n--- Step 1: Reset the project (POST /demo/reset) ---")
    res_reset1 = http_request("/demo/reset", method="POST")
    print(f"Status: {res_reset1['status_code']}")
    print(json.dumps(res_reset1["body"], indent=2))

    # Step 2: Display initial funding, current tranche, released amount, verified spend, and freeze state
    print("\n--- Step 2: Display initial project state (GET /projects/WATER-001) ---")
    res_proj_initial = http_request("/projects/WATER-001")
    print(f"Status: {res_proj_initial['status_code']}")
    p_init = res_proj_initial["body"]
    print(
        f"Project: {p_init['name']} ({p_init['id']})\n"
        f"  Funding (wei):        {p_init['funding_wei']} ({int(p_init['funding_wei']) / 10**18:.1f} ETH)\n"
        f"  Current Tranche:      {p_init['current_tranche']} / {p_init['total_tranches']}\n"
        f"  Released (wei):       {p_init['released_wei']} ({int(p_init['released_wei']) / 10**18:.1f} ETH)\n"
        f"  Verified Spend (wei): {p_init['verified_spend_wei']} (${p_init['verified_spend_usd_cents'] / 100:.2f} USD)\n"
        f"  Is Frozen:            {p_init['is_frozen']}"
    )

    # Step 3: Attempt the first tranche release and show the real result
    print("\n--- Step 3: Attempt first tranche release (POST /projects/WATER-001/release) ---")
    res_release_t1 = http_request("/projects/WATER-001/release", method="POST")
    print(f"Status: {res_release_t1['status_code']}")
    print(json.dumps(res_release_t1["body"], indent=2))

    # Step 4: Submit a valid signed claim (with verified evidence commitment)
    print("\n--- Step 4: Submit valid signed claim with verified evidence (POST /demo/scenarios/valid_claim/run) ---")
    res_valid = http_request("/demo/scenarios/valid_claim/run", method="POST")
    print(f"Status: {res_valid['status_code']}")
    print(json.dumps(res_valid["body"], indent=2))

    # Step 5: Attempt the next tranche release and show the actual spending threshold and outcome
    print("\n--- Step 5: Attempt next tranche release (POST /projects/WATER-001/release) ---")
    res_release_t2 = http_request("/projects/WATER-001/release", method="POST")
    print(f"Status: {res_release_t2['status_code']}")
    print(json.dumps(res_release_t2["body"], indent=2))

    # Step 6: Trigger a qualifying security attack (Cross-report duplicate invoice reuse)
    print("\n--- Step 6: Trigger qualifying security attack (POST /demo/scenarios/duplicate_report/run) ---")
    res_dup = http_request("/demo/scenarios/duplicate_report/run", method="POST")
    print(f"Status: {res_dup['status_code']}")
    print(json.dumps(res_dup["body"], indent=2))

    # Step 7: Attempt release again and show that the freeze blocks it
    print("\n--- Step 7: Attempt release while project is frozen (POST /projects/WATER-001/release) ---")
    res_release_frozen = http_request("/projects/WATER-001/release", method="POST")
    print(f"Status: {res_release_frozen['status_code']}")
    print(json.dumps(res_release_frozen["body"], indent=2))

    # Step 8: Fetch and display the complete end-to-end fund trace graph
    print("\n--- Step 8: Display complete fund trace graph (GET /projects/WATER-001/trace) ---")
    res_trace = http_request("/projects/WATER-001/trace")
    print(f"Status: {res_trace['status_code']}")
    trace_body = res_trace["body"]
    print(f"Trace Graph Conservation: {trace_body.get('is_conserved')}")
    print(f"Discrepancies: {len(trace_body.get('discrepancies', []))}")
    print("Summary:")
    print(json.dumps(trace_body.get("summary", {}), indent=2))
    print("Events Chain:")
    for e in trace_body.get("events", []):
        parent_str = f"<- parent {e['parent_event_id']}" if e.get("parent_event_id") else "(root)"
        sim_str = "[SIMULATED]" if e.get("is_simulated") else "[REAL]"
        print(f"  [{e['event_type']}] {e['event_id']} {parent_str}: {e['input_amount']} {e['input_asset']} -> {e['output_amount']} {e['output_asset']} {sim_str}")

    # Step 9: System metrics inspection
    print("\n--- Step 9: System metrics (GET /metrics) ---")
    res_metrics = http_request("/metrics")
    print(f"Status: {res_metrics['status_code']}")
    print(json.dumps(res_metrics["body"], indent=2))

    # Step 10: Reset confirmation (Confirm repeatability & idempotency)
    print("\n--- Step 10: Reset project again to confirm clean repeatability (POST /demo/reset) ---")
    res_reset2 = http_request("/demo/reset", method="POST")
    print(f"Status: {res_reset2['status_code']}")
    print(json.dumps(res_reset2["body"], indent=2))

    print("\n=== TRACE LIVE API VERIFICATION COMPLETE ===")


if __name__ == "__main__":
    main()
