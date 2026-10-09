def load():
    try:
        from pkg import _native
    except ImportError:
        return None
    return _native
