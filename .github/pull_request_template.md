#### Title
<!-- Start with a tag: [ENH], [MNT], [DOC], [BUG], [SEC], or [BREAKING] — e.g. "[ENH] Add spam detector" -->

#### Reference Issues/PRs
<!--
Example: Fixes #1234. See also #5678.

Please use keywords (e.g., Fixes) to create link to the issues or pull requests
you resolved, so that they will automatically be closed when your pull request
is merged. See https://github.com/blog/1506-closing-issues-via-pull-requests.
If no issue exists, you can open one here: https://github.com/ksharma6/Inbox0/issues
-->

#### Type of change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation only

#### What does this implement/fix? Explain your changes.
<!--
A clear and concise description of what you have implemented.
-->

#### Does your contribution introduce a new dependency? If yes, which one?

#### What should a reviewer concentrate their feedback on?
<!-- If this PR is a draft or work-in-progress, call out which parts are ready for review and which are not. Use bullets or checkboxes. -->

#### Did you add any tests for the change?
<!-- It is considered good practice to add tests with newly added code to enforce the fact that the code actually works. This will reduce the chance of introducing logical bugs. -->

#### PR checklist
- [ ] The PR title starts with either [ENH], [MNT], [DOC], [BUG], [SEC], or [BREAKING]
    - [BUG] - bugfix
    - [MNT] - CI, test framework, dependency updates
    - [ENH] - adding or improving code
    - [DOC] - writing or improving documentation or docstrings
    - [SEC] - security fixes or vulnerability patches
    - [BREAKING] - any change that requires user to update their setup or code 
- [ ] Tests added or updated for any changed behaviour
- [ ] No secrets, credentials, or `.env` values committed
- [ ] `pyproject.toml` updated if new dependencies were added and `uv.lock` regenerated via `uv sync`