"""Every command a workflow runs must be one its script accepts.

paper_trading's --timeframe choices were derived from a dict in another
module. That dict grew a market layer, the choices silently became
{crypto, nse}, and every scheduled tick died on `--timeframe 30m` - its
own default. Nothing in the suite touched an argument parser, so it took a
Discord failure notice to find out.
"""
import importlib
import pathlib
import re
import shlex
import unittest

WORKFLOWS = pathlib.Path(".github/workflows")


def scheduled_commands():
    """(workflow, script, argv) for every python call in every workflow."""
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        joined = workflow.read_text(encoding="utf-8").replace("\\n", " ")
        for line in joined.splitlines():
            match = re.search(r"python\s+([a-z_]+\.py)(.*)", line)
            if not match:
                continue
            script, rest = match.group(1), match.group(2).strip()
            # ${VAR:-default} is what a scheduled run gets: the default.
            rest = re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", rest)
            try:
                tokens = shlex.split(rest)
            except ValueError:
                continue
            # A value that is still a shell variable cannot be checked,
            # and dropping it alone would orphan its flag into looking
            # like a flag with a missing argument.
            cleaned = []
            skip_next = False
            for index, token in enumerate(tokens):
                if skip_next:
                    skip_next = False
                    continue
                following = tokens[index + 1] if index + 1 < len(tokens) else ""
                if token.startswith("--") and "$" in following:
                    skip_next = True
                    continue
                if "$" in token:
                    continue
                cleaned.append(token)
            yield workflow.name, script, cleaned


class WorkflowCommandTests(unittest.TestCase):
    def test_every_referenced_script_exists(self):
        for workflow, script, _ in scheduled_commands():
            with self.subTest(workflow=workflow, script=script):
                self.assertTrue(
                    pathlib.Path(script).exists(),
                    f"{workflow} runs {script}, which is not in the repo",
                )

    def test_every_scheduled_command_parses(self):
        for workflow, script, tokens in scheduled_commands():
            module = importlib.import_module(script[:-3])
            parse_args = getattr(module, "parse_args", None)
            if parse_args is None:
                continue
            with self.subTest(workflow=workflow, script=script, argv=tokens):
                try:
                    parse_args(tokens)
                except SystemExit as exit_error:
                    self.fail(
                        f"{workflow} runs `{script} {' '.join(tokens)}` "
                        f"but its own parser rejects it ({exit_error})"
                    )

    def test_the_commands_are_actually_being_found(self):
        # A regex that quietly matched nothing would make the tests above
        # pass while checking not one command.
        found = {script for _, script, _ in scheduled_commands()}
        self.assertIn("scanner.py", found)
        self.assertIn("paper_trading.py", found)
        self.assertGreaterEqual(len(found), 6)


if __name__ == "__main__":
    unittest.main()
