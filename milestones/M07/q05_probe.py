"""Is q05's decline REPRODUCIBLE or a flake? Ask staging directly, three times.

Two consecutive CI runs had q05 DECLINE at confidence 0.00. That is either
run-to-run non-determinism (the finding as filed) or a real current regression
(a different finding entirely, and a worse one). Three direct calls settle it
for ~$0.03 instead of $0.20 a run.

Cache is bypassed both ways, exactly as run_evals.ask() does — otherwise the
second and third calls measure the cache rather than the system.
"""
import json
import urllib.request

API = "https://7o8mote0q6.execute-api.us-west-2.amazonaws.com/api"
Q = ("What are the two main criteria a food must meet to use the 'healthy' "
     "claim under the updated rule?")


def ask(question):
    req = urllib.request.Request(
        f"{API}/query",
        data=json.dumps({"question": question, "no_cache": True}).encode(),
        headers={"Content-Type": "application/json",
                 "x-regdelta-no-cache": "1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


for i in range(1, 4):
    try:
        r = ask(Q)
    except Exception as e:
        print(f"call {i}: TRANSPORT ERROR {e}")
        continue
    ans = (r.get("answer") or "").strip()
    print(f"--- call {i} ---")
    print("  status     :", r.get("status"))
    print("  confidence :", r.get("confidence"))
    print("  review     :", r.get("review_reason"))
    print("  tier       :", r.get("tier"), "| cache:", r.get("cache"),
          "| fallback:", r.get("fallback_reason"))
    print("  citations  :", r.get("citations"))
    print("  answer len :", len(ans))
    print("  answer[:200]:", ans[:200].replace("\n", " "))
