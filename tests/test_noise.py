import pytest

from jarvis_ai.textprep import noise


@pytest.mark.parametrize("t", ["Hmm.", "Mmm.", "hm", "Uh...", "Um, uh.", "Hmm, hmm.", "Thank you.", "...", ""])
def test_dropped(t):
    assert noise(t)


@pytest.mark.parametrize("t", ["Mm-hmm.", "Uh-huh.", "Yes.", "Stop.", "Hmm, read it all.", "Ah, I see.", "Um, what is this project?", "M."])
def test_kept(t):
    assert not noise(t)
