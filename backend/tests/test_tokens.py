from app.services.token_service import generate_token, normalise_token


def test_generated_token_normalises():
    t = generate_token()
    assert t.startswith("SQ-")
    body = normalise_token(t)
    assert body is not None and len(body) == 32


def test_forgiving_input():
    t = generate_token()
    assert normalise_token(t.lower().replace("-", " ")) == normalise_token(t)


def test_typo_and_junk_rejected():
    t = generate_token()
    flipped = t[:-1] + ("A" if t[-1] != "A" else "B")
    assert normalise_token(flipped) is None
    for bad in ["", "SQ", "x" * 200, "SQ-" + "A" * 36, None, 12]:
        assert normalise_token(bad) is None  # type: ignore[arg-type]


def test_tokens_are_unique():
    assert len({generate_token() for _ in range(200)}) == 200


def test_hash_stable_and_distinct(crypto):
    a, b = normalise_token(generate_token()), normalise_token(generate_token())
    assert crypto.hash_token(a) == crypto.hash_token(a)
    assert crypto.hash_token(a) != crypto.hash_token(b)
