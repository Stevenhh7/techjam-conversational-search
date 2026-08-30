from __future__ import annotations

from experiments.frozen import verify_manifest


def main() -> None:
    errors = verify_manifest()
    if errors:
        raise SystemExit("frozen dataset verification failed:\n- " + "\n- ".join(errors))
    print("Frozen dataset hashes and sample counts verified.")


if __name__ == "__main__":
    main()
