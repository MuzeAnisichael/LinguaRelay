from lingua_relay.correction.benchmark import run_fault_gate_benchmark


def test_m4_fault_gates_pass() -> None:
    report = run_fault_gate_benchmark(4)

    assert report["acceptance"]["all_passed"] is True  # type: ignore[index]
