import sys


def main() -> int:
    # Keep diagnostics ahead of GUI/config imports so a broken bundle reports
    # its own failure without opening the normal app or touching user data.
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        from lingua_relay.self_test import main as self_test_main

        return self_test_main(sys.argv[2:])

    from lingua_relay.ui.app import run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
