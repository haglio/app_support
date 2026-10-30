"""What a module of Python defines, and what it uses of a package.  Every package,
module and name here is invented."""
from __future__ import annotations

from app_support.python_source import names_defined, references


class TestNamesDefined:
    def test_a_module_defines_its_functions_classes_assignments_and_imports(self):
        source = (
            "import os\n"
            "from pathlib import Path as P\n"
            "GRAY = 1\n"
            "LIGHT: int = 2\n"
            "def tint(): pass\n"
            "async def fade(): pass\n"
            "class Palette: pass\n"
        )

        assert names_defined(source) == {"os", "P", "GRAY", "LIGHT", "tint", "fade", "Palette"}

    def test_a_name_bound_under_a_module_level_if_try_or_with_is_the_modules(self):
        source = (
            "import sys\n"
            "if sys.platform == 'win32':\n"
            "    SEPARATOR = '\\\\'\n"
            "else:\n"
            "    SEPARATOR = '/'\n"
            "try:\n"
            "    import fastlib as engine\n"
            "except ImportError:\n"
            "    engine = None\n"
            "with open(__file__) as handle:\n"
            "    FIRST_LINE = handle.readline()\n"
        )

        assert names_defined(source) == {"sys", "SEPARATOR", "engine", "handle", "FIRST_LINE"}

    def test_what_a_function_or_class_binds_inside_itself_is_not_the_modules(self):
        source = (
            "def tint():\n"
            "    shade = 1\n"
            "    return shade\n"
            "class Palette:\n"
            "    WARM = 2\n"
        )

        assert names_defined(source) == {"tint", "Palette"}


class TestReferences:
    def test_a_name_imported_from_a_module_of_the_package_is_used(self):
        source = "from widgetlib.colors import GRAY, tint as shade\nfrom elsewhere import thing\n"

        assert references(source, ("widgetlib",)) == {"widgetlib.colors.GRAY", "widgetlib.colors.tint"}

    def test_what_is_reached_through_an_imported_module_is_used_whatever_it_is_called_here(self):
        source = (
            "import widgetlib.colors\n"
            "import widgetlib.parts as parts\n"
            "from widgetlib import hinges\n"
            "import os\n"
            "widgetlib.colors.GRAY.value\n"
            "parts.Lever()\n"
            "hinges.OPEN\n"
            "os.path.join\n"
        )

        assert references(source, ("widgetlib",)) == {
            "widgetlib.colors", "widgetlib.colors.GRAY.value", "widgetlib.parts", "widgetlib.parts.Lever",
            "widgetlib.hinges", "widgetlib.hinges.OPEN"}

    def test_a_string_spelling_out_a_dotted_name_of_the_package_uses_it(self):
        source = (
            '"""widgetlib.docs is only mentioned here."""\n'
            'patch("widgetlib.colors.GRAY", 2)\n'
            'ENTRY = "widgetlib.cli:main"\n'
            'COMMAND = ["python", "-m widgetlib.tools.serve", "--quiet"]\n'
            'NOTE = "widgetlibrary.thing is another package"\n'
        )

        assert references(source, ("widgetlib",)) == {
            "widgetlib.colors.GRAY", "widgetlib.cli.main", "widgetlib.tools.serve"}
