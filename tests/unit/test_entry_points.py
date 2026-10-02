from unskein.entry_points import script_modules_of


def test_scripts_and_gui_scripts_give_their_modules() -> None:
    project = {
        "scripts": {"a": "pkg.cli:main", "b": "pkg.cli:other"},
        "gui-scripts": {"g": "pkg.gui:run"},
    }
    assert script_modules_of(project) == ("pkg.cli", "pkg.gui")


def test_target_without_a_function_is_the_module_itself() -> None:
    assert script_modules_of({"scripts": {"a": "pkg.tool"}}) == ("pkg.tool",)


def test_unusable_scripts_give_no_entry_points_and_no_crash() -> None:
    assert script_modules_of({"scripts": "not a table"}) == ()
    assert script_modules_of({"scripts": {"a": 3, "b": ""}}) == ()


def test_a_missing_or_malformed_project_table_gives_nothing() -> None:
    assert script_modules_of(None) == ()
    assert script_modules_of(["not", "a", "table"]) == ()
