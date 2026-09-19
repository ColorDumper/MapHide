"""Tests for the OS-level guard against two copies of MapHide running at once."""

import uuid

from maphide import single_instance


def _unique_name():
    # A real Windows named mutex, scoped to this one test so runs can never
    # see a name a previous test (or the real app) already holds.
    return f"Local\\MapHide-Test-{uuid.uuid4().hex}"


def test_the_first_acquire_of_a_name_succeeds():
    assert single_instance.acquire(_unique_name()) is True


def test_a_second_acquire_of_the_same_name_reports_already_running():
    name = _unique_name()
    assert single_instance.acquire(name) is True
    assert single_instance.acquire(name) is False


def test_two_different_names_do_not_interfere():
    assert single_instance.acquire(_unique_name()) is True
    assert single_instance.acquire(_unique_name()) is True
