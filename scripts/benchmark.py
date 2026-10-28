"""Compare equivalent user responses; pace requests below gateway rate limit."""
import argparse
import json
import statistics
import time
from urllib.request import Request, urlopen
from issue_token import create_token

parser = argparse.ArgumentParser()
parser.add_argument("--samples", type=int, default=30)
args = parser.parse_args()
if args.samples < 2:
    parser.error("--samples must be at least 2")
token = create_token()
results = {"direct": [], "gateway": []}
time.sleep(1.1)
for index in range(args.samples + 3):
    pair = [("direct", "http://localhost:8001/users/1"), ("gateway", "http://localhost:8080/users/1")]
    if index % 2:
        pair.reverse()
    for name, url in pair:
        start = time.perf_counter()
        with urlopen(Request(url, headers={"Authorization": f"Bearer {token}"}), timeout=10) as response:
            assert json.load(response)["id"] == "1"
        elapsed = (time.perf_counter() - start) * 1000
        if index >= 3:
            results[name].append(elapsed)
    time.sleep(0.15)
summary = {}
for name, values in results.items():
    summary[name] = {"samples": len(values), "mean_ms": round(statistics.mean(values), 3),
                     "p50_ms": round(statistics.median(values), 3),
                     "p95_ms": round(sorted(values)[min(len(values)-1, __import__('math').ceil(len(values)*.95)-1)], 3)}
summary["mean_overhead_ms"] = round(summary["gateway"]["mean_ms"] - summary["direct"]["mean_ms"], 3)
print(json.dumps(summary, indent=2))
with open("benchmark-results.json", "w") as output:
    json.dump({"summary": summary, "raw_ms": results}, output, indent=2)
