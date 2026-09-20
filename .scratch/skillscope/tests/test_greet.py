from greet import greet


def test_greet_simple():
    assert greet('Bob') == 'Hello, Bob!'
