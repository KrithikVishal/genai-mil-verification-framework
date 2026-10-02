import json, sys
sys.stdout.reconfigure(encoding='utf-8')
for i in [1, 2]:
    rpath = f'mvp/artifacts/ACC-REQ-001-T1-I{i}_result.json'
    ipath = f'mvp/artifacts/ACC-REQ-001-T1-I{i}_intent.json'
    with open(rpath) as f:
        r = json.load(f)
    with open(ipath) as f:
        intent = json.load(f)

    verdict = r["requirement_verdict"]
    metrics = r["measured_metrics"]
    oracle_conds = r.get("oracle_conditions", [])
    oracle = intent["oracle"]
    ic = intent["stimulus"]["initial_conditions"]

    print(f"=== Iteration {i} ===")
    print(f"Verdict : {verdict}")
    print(f"v_set={ic['v_set_mps']}  v_ego_init={ic['v_ego_init_mps']}  d_init={ic['d_init_m']}")
    print(f"Oracle window: {oracle['evaluation_window_start_s']}s -> {oracle['evaluation_window_end_s']}s  (duration={intent['duration_s']}s)")
    print("Metrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    print("Oracle conditions:")
    for c in oracle_conds:
        if isinstance(c, dict):
            mark = "PASS" if c.get("passed") else "FAIL"
            print(f"  [{mark}] {c['signal']} {c['operator']} {c['threshold']}  measured={c.get('measured', '?'):.4f}" if isinstance(c.get('measured'), float) else f"  [{mark}] {c['signal']} {c['operator']} {c['threshold']}")
    for w in r.get('warnings', []):
        print(f"  WARN: {w}")
    print()
