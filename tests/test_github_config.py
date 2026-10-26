import pytest

from app.git_service import normalize_github_repository


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Pustoylst/agent-ci-fixture", "Pustoylst/agent-ci-fixture"),
        ("https://github.com/Pustoylst/agent-ci-fixture", "Pustoylst/agent-ci-fixture"),
        ("https://github.com/Pustoylst/agent-ci-fixture.git", "Pustoylst/agent-ci-fixture"),
    ],
)
def test_normalize_github_repository(value: str, expected: str) -> None:
    assert normalize_github_repository(value) == expected


def test_normalize_github_repository_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        normalize_github_repository("not-a-repository")