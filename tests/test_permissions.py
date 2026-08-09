import pytest

from app.security.permissions import PermissionChecker, PermissionLevel


def test_read_only_does_not_require_confirmation():
    checker = PermissionChecker()
    assert checker.requires_confirmation(PermissionLevel.READ_ONLY) is False


def test_low_risk_does_not_require_confirmation():
    checker = PermissionChecker()
    assert checker.requires_confirmation(PermissionLevel.LOW_RISK) is False


def test_confirm_required_requires_confirmation():
    checker = PermissionChecker()
    assert checker.requires_confirmation(PermissionLevel.CONFIRM_REQUIRED) is True


def test_always_confirm_requires_confirmation():
    checker = PermissionChecker()
    assert checker.requires_confirmation(PermissionLevel.ALWAYS_CONFIRM) is True
