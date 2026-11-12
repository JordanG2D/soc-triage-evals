"""Run the recorded development slice through the native Inspect task runner."""

import argparse

from inspect_ai import eval

from soc_triage.inspect_task import soc_triage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", default=".cache/model2vec")
    parser.add_argument("--log-dir", default="artifacts/recorded/inspect")
    args = parser.parse_args()
    logs = eval(
        soc_triage(model_path=args.model_path), log_dir=args.log_dir, log_format="json",
        max_samples=1, fail_on_error=True, retry_on_error=0,
        ctl_server=False, acp_server=False, log_model_api=False,
    )
    if not logs or any(log.status != "success" for log in logs):
        raise SystemExit("Recorded Inspect evaluation failed; inspect its log")
    print(f"Recorded mechanics evaluation completed: {sum(len(log.samples or []) for log in logs)} samples")


if __name__ == "__main__":
    main()
