"""Run the reviewed CRG build API and preserve its structured failure result."""
import json
import sys

PREFIX = "AIDEV_CRG_RESULT="


def main():
    from code_review_graph.tools.build import build_or_update_graph

    operation, root = sys.argv[1:3]
    if operation not in ("build", "update"):
        raise ValueError("Unsupported operation")
    result = build_or_update_graph(full_rebuild=operation == "build", repo_root=root, postprocess="minimal")
    print(PREFIX + json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("status") == "ok" and not result.get("errors") and not result.get("warnings") else 1


if __name__ == "__main__":
    raise SystemExit(main())
