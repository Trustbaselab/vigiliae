import sys, json
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
print(json.dumps({"stub": True, "prompt_head": prompt[:200]}, ensure_ascii=False))
