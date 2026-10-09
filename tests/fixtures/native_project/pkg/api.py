from pkg._speed import fast_sum
from pkg.stubonly import X
from pkg.fast import _impl
import pkg._cy


def tokenize(text):
    from pkg._native import Tokenizer

    return Tokenizer(text), fast_sum, X, _impl, pkg._cy.go()
