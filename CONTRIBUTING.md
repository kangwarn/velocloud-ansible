# Contributing

## Code of Conduct

This project follows the [Ansible Community Code of Conduct](https://docs.ansible.com/projects/ansible/latest/community/code_of_conduct.html).

## Development

Python 3.14 is required (see `.python-version`). The collection root is the git root.

```sh
uv sync
uv run pytest -q
uv run black plugins tests
uv run ansible-galaxy collection build . --output-path dist
```

Sanity tests use `ansible-test`. GitHub Actions runs them in Docker via
`ansible-community/ansible-test-gh-action`. Locally, `ansible-test` needs the
collection at `ansible_collections/velocloud/api/` (not the git root). Copy the
tree and point `ANSIBLE_TEST_CONTENT_ROOT` at that copy; `uv run` resets the
working directory to the project root.

```sh
rm -rf .sanity-tree
mkdir -p .sanity-tree/ansible_collections/velocloud/api
rsync -a --exclude .venv --exclude .git --exclude tests/output --exclude dist \
  --exclude .sanity-tree ./ .sanity-tree/ansible_collections/velocloud/api/
ANSIBLE_TEST_CONTENT_ROOT="$PWD/.sanity-tree/ansible_collections/velocloud/api" \
  uv run ansible-test sanity --python 3.14 --lint
```

If Docker is available, this is the equivalent of CI (Python 3.14 only):

```sh
ANSIBLE_TEST_CONTENT_ROOT="$PWD/.sanity-tree/ansible_collections/velocloud/api" \
  uv run ansible-test sanity --docker default --python 3.14 -v
```

Do not omit `--python 3.14`. ansible-test otherwise compiles and imports on
every controller Python for that ansible-core release.

## Pull requests

- Follow the versioning policy in the README: bugfixes are patches, features are minor, breaking changes are major.
- Add or update tests for behaviour changes.
- Keep `DOCUMENTATION`, `EXAMPLES`, and `RETURN` aligned with each module's argument spec.
- Do not echo VCO error or login bodies; they can contain credentials or activation keys.
- Register results that may contain activation keys with `no_log: true` in examples.
- File bugs and feature requests in [GitHub Issues](https://github.com/kangwarn-arista/velocloud-ansible/issues).
