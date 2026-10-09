def load():
    try:
        import core_plugins.extra
    except ImportError:
        return None
    return core_plugins.extra
