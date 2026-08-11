from lingua_relay.correction.controls import CircuitBreaker, RateLimiter


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_rate_limiter_refills_without_blocking() -> None:
    clock = Clock()
    limiter = RateLimiter(2, clock=clock)

    assert limiter.acquire()
    assert limiter.acquire()
    assert not limiter.acquire()
    clock.value = 30
    assert limiter.acquire()


def test_circuit_breaker_opens_and_allows_one_recovery_probe() -> None:
    clock = Clock()
    circuit = CircuitBreaker(2, 10, clock=clock)

    circuit.record_failure()
    assert circuit.allow_request()
    circuit.record_failure()
    assert circuit.snapshot().state == "open"
    assert not circuit.allow_request()
    clock.value = 10
    assert circuit.allow_request()
    assert not circuit.allow_request()
    circuit.record_success()
    assert circuit.snapshot().state == "closed"
