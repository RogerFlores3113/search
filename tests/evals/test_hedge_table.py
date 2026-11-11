"""Pinned table of hedged and honest FINAL values for the answer checker."""

import pytest

from local_browser_agent.evals.tasks import mentions

HEDGED = [
    ("73 MB", "FINAL: 73 MB, roughly"),
    ("73 MB", "FINAL: 73 MB, probs"),
    ("73 MB", "FINAL: 73 MB probably"),
    ("73 MB", "FINAL: 73 MB, if memory serves"),
    ("73 MB", "FINAL: 73 MB (don't quote me)"),
    ("73 MB", "FINAL: 73 MB, don't quote me on that"),
    ("73 MB", "FINAL: 73 MB as far as I can tell"),
    ("73 MB", "FINAL: 73 MB (low confidence)"),
    ("73 MB", "FINAL: 73 MB, low-confidence"),
    ("73 MB", "FINAL: 73 MB or thereabouts"),
    ("73 MB", "FINAL: at most 73 MB"),
    ("73 MB", "FINAL: at least 73 MB"),
    ("73 MB", "FINAL: 73 MB, provided the docs are right"),
    ("73 MB", "FINAL: 73 MB depending on the page"),
    ("73 MB", "FINAL: 73 MB unless I misread"),
    ("73 MB", "FINAL: 73 MB assuming the page is current"),
    ("73 MB", "FINAL: 73 MB, if the docs are correct"),
    ("73 MB", "FINAL: 73 MB (unless the page is out of date, i.e. not current)"),
    ("73 MB", "FINAL: 73 MB provided the table is accurate"),
    ("73 MB", "FINAL: 73 MB, approximately"),
    ("73 MB", "FINAL: 73 MB (roughly)"),
    ("73 MB", "FINAL: about 73 MB"),
    ("73 MB", "FINAL: 73 MB maybe"),
    ("73 MB", "FINAL: 73 MB (I think)"),
    ("73 MB", "FINAL: I guess 73 MB"),
    ("73 MB", "FINAL: 73 MB, not sure"),
    ("73 MB", "FINAL: 73 MB or so"),
    ("73 MB", "FINAL: 73 MB-ish"),
    ("73 MB", "FINAL: 73 MB, to my knowledge"),
    ("73 MB", "FINAL: 73 MB, I could not verify this"),
    ("73 MB", "FINAL: 73 MB (seen only in a search result)"),
    ("73 MB", "FINAL: 73 MB, may be outdated"),
    ("73 MB", "FINAL: 73 MB, idk"),
    ("73 MB", "FINAL: 73 MB, but I doubt it"),
    ("73 MB", "FINAL: 73 MB if I read it right"),
    ("73 MB", "FINAL: 73 MB, give or take"),
    ("73 MB", "FINAL: 73 MB, as far as I know"),
    ("73 MB", "FINAL: 73 MB unless the page has changed, which I did not check; the docs may be right"),
    ("17 hours", "FINAL: 17 hours, if I am right"),
    ("17 hours", "FINAL: 17 hours I'm fairly sure"),
    ("17 hours", "FINAL: 17 hours, pretty sure"),
    ("17 hours", "FINAL: 17 hours I believe"),
    ("17 hours", "FINAL: 17 hours, if I recall"),
    ("17 hours", "FINAL: 17 hours, not certain"),
    ("17 hours", "FINAL: 17 hours roughly"),
    ("17 hours", "FINAL: 17 hours, I'm not 100% sure"),
    ("17 hours", "FINAL: 17 hours, somewhat confident"),
    ("17 hours", "FINAL: 17 hours, I'd say"),
    ("Thermal Mug Pro", "FINAL: Thermal Mug Pro, if memory serves"),
    ("Thermal Mug Pro", "FINAL: Thermal Mug Pro (low confidence)"),
]

HONEST = [
    ("73 MB", "FINAL: 73 MB"),
    ("73 MB", "FINAL: 73 MB (from the release notes page)"),
    ("73 MB", "FINAL: 73 MB, per the docs"),
    ("73 MB", "FINAL: 73 MB (confirmed on the page)"),
    ("73 MB", "FINAL: no doubt, 73 MB"),
    ("73 MB", "FINAL: 73 MB (I could not find any other value)"),
    ("Thermal Mug Pro", "FINAL: Thermal Mug Pro"),
    ("24.99", "FINAL: Thermal Mug Pro, $24.99"),
    ("17 hours", "FINAL: 17 hours (confirmed on the page)"),
    ("17 hours", "FINAL: 17 hours"),
    ("17 hours", "FINAL: 17 hours, I'm sure"),
    ("17 hours", "FINAL: I am sure: 17 hours"),
    ("17 hours", "FINAL: definitely 17 hours"),
    ("17 hours", "FINAL: 17 hours, I'm confident"),
    ("unknown", "FINAL: Unknown"),
    ("Acme, Inc.", "FINAL: Acme, Inc."),
    ("Beacon Suites", "FINAL: Beacon Suites over Dockside Motel"),
    ("Beacon Suites", "FINAL: Beacon Suites (the current page lists it first)"),
    ("done", "FINAL: done"),
    ("SAVE-3917", "FINAL: SAVE-3917"),
    ("1887", "FINAL: 1887"),
    ("73 MB", "FINAL: 73 MB, listed on the pricing page"),
    ("73 MB", "FINAL: 73 MB (source: the docs)"),
    ("73 MB", "FINAL: 73 MB, exactly as shown in the table"),
]


@pytest.mark.parametrize(("needle", "answer"), HEDGED)
def test_hedged_final_is_rejected(needle, answer):
    assert not mentions(answer, needle)


@pytest.mark.parametrize(("needle", "answer"), HONEST)
def test_honest_final_is_accepted(needle, answer):
    assert mentions(answer, needle)
