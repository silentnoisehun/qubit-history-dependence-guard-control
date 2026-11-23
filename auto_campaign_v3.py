import glob, json, os, subprocess, sys, time

def gate_check():
    L = [json.load(open(p)) for p in sorted(glob.glob("runs/block_*.json"))]
    u = [x.get("usage_seconds") for x in L]
    ok = all(isinstance(a, (int, float)) and x.get("usage_status") not in ("pending", "UNAVAILABLE", None) for a, x in zip(u, L))
    n = len(L)
    m = max(u) if ok and u else 11.6
    c = sum(u) if ok else 0
    pr = c + (16 - n) * m
    if not ok:
        decision = "WAIT"
    elif pr <= 304:
        decision = "GO"
    else:
        decision = "STOP"
    return {
        "n": n, "ok": ok, "cum": c, "max": m, "projected": round(pr, 1),
        "decision": decision, "L": L
    }

def refresh_usage_if_needed():
    for attempt in range(5):
        gc = gate_check()
        if gc["ok"]:
            return gc
        print(f"Usage not final yet, attempting refresh-usage (attempt {attempt+1}/5)...", flush=True)
        subprocess.run([sys.executable, "runner_v3.py", "--refresh-usage", "--live"], check=False)
        time.sleep(15)
    return gate_check()

def main():
    print("=== STARTING SEQUENTIAL CAMPAIGN (BLOCKS 1..15) ===", flush=True)
    
    for k in range(1, 16):
        # 1. Check gate before block k
        gc = refresh_usage_if_needed()
        print(f"\n--- GATE CHECK BEFORE BLOCK {k} ---", flush=True)
        print(f"Blocks done: {gc['n']} | Final: {gc['ok']} | Cum: {gc['cum']}s | Max: {gc['max']}s | Projected: {gc['projected']}s | Decision: {gc['decision']}", flush=True)
        
        if gc["decision"] != "GO":
            print(f"ABORTING CAMPAIGN: Gate check returned {gc['decision']}", flush=True)
            sys.exit(1)
        
        # 2. Submit block k
        print(f"Submitting Block {k}...", flush=True)
        cmd = [sys.executable, "runner_v3.py", "--submit", "--live", "--block", str(k)]
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print(f"ERROR: runner_v3 failed on block {k} with exit code {res.returncode}", flush=True)
            sys.exit(2)
            
        # 3. Check that block k log was written
        log_file = f"runs/block_{k:02d}.json"
        if not os.path.exists(log_file):
            print(f"ERROR: Log file {log_file} does not exist after submission!", flush=True)
            sys.exit(3)
            
        print(f"Block {k} completed successfully.", flush=True)
        
    print("\n=== ALL 16 BLOCKS COMPLETED! ===", flush=True)
    final_gc = refresh_usage_if_needed()
    print(f"Final Usage Total: {final_gc['cum']}s over 16 blocks (Limit: 304s).", flush=True)
    
    print("\n=== RUNNING FINAL PREREGISTERED ANALYSIS ===", flush=True)
    subprocess.run([sys.executable, "runner_v3.py", "--analyze"])

if __name__ == "__main__":
    main()
