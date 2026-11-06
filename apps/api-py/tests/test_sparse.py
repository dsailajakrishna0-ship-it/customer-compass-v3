from app.rag import sparse


def test_words_are_lower_cased_and_punctuation_is_dropped():
    assert sparse.tokenize("Renewal: Acme's Q4 deal (ACME-42)!") == [
        "renewal", "acme", "s", "q4", "deal", "acme", "42",
    ]  # fmt: skip


def test_the_same_word_always_gets_the_same_index():
    # a stable hash, not Python's per-run randomised hash(): stored vectors stay valid after a restart
    assert sparse.term_index("renewal") == sparse.term_index("renewal")
    assert (
        sparse.term_index("renewal") == 4244916168
    )  # pinned: changing this invalidates stored data


def _weight(text: str, word: str) -> float:
    vector = sparse.document_vector(text)
    return vector.values[vector.indices.index(sparse.term_index(word))]


def test_a_repeated_word_counts_more_but_with_diminishing_returns():
    pad = "x " * 100  # the same filler everywhere, so only the repeats differ
    w1, w2, w3 = (_weight(" ".join(["pricing"] * n) + " " + pad, "pricing") for n in (1, 2, 3))
    assert w1 < w2 < w3
    assert (w2 - w1) > (w3 - w2)  # each extra repeat adds less than the one before


def test_a_long_chunk_does_not_win_just_by_being_long():
    short = sparse.document_vector("renewal " + "x " * 9)
    long = sparse.document_vector("renewal " + "x " * 399)
    i = sparse.term_index("renewal")
    assert short.values[short.indices.index(i)] > long.values[long.indices.index(i)]


def test_a_query_vector_has_each_distinct_word_once_with_weight_one():
    q = sparse.query_vector("acme acme renewal")
    assert len(q.indices) == 2 and q.values == [1.0, 1.0]
    assert q.indices == sorted(q.indices)


def test_a_question_with_no_words_gives_an_empty_vector():
    assert sparse.query_vector("?!").indices == []
