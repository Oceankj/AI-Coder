"""Condensed TAP evidence retains structured assertion differences."""

from ai_coder.orchestration.tdd import check_evidence


def test_condensed_tap_retains_node_array_values_and_test_frame():
    log = "\n".join((
        "TAP version 13",
        "not ok 1 - preserves the chosen playlist order",
        "  ---",
        "  location: '/tmp/music/tests/integration-contract.test.js:32:1'",
        "  error: |-",
        "    Expected values to be strictly deep-equal:",
        "    + actual - expected",
        "  code: 'ERR_ASSERTION'",
        "  expected:",
        "    0: 'Second'",
        "    1: 'First'",
        "  actual:",
        "    0: 'First'",
        "    1: 'Second'",
        "  operator: 'deepStrictEqual'",
        "  stack: |-",
        "    async Test.run (node:internal/test_runner/test:1113:7)",
        "    TestContext.<anonymous> (file:///tmp/music/tests/integration-contract.test.js:60:10)",
        "  ...",
        "test noise\n" * 600,
        "# pass 22",
        "# fail 1",
    ))

    evidence = check_evidence(log)

    assert "  expected:\n    0: 'Second'\n    1: 'First'" in evidence
    assert "  actual:\n    0: 'First'\n    1: 'Second'" in evidence
    assert "integration-contract.test.js:32:1" in evidence
    assert "TestContext.<anonymous> (file:///tmp/music/tests/integration-contract.test.js:60:10)" in evidence
    assert "node:internal" not in evidence
    assert "# fail 1" in evidence
    assert len(evidence) <= 4000
