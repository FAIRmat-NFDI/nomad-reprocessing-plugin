# nomad-reprocessing-plugin

A NOMAD plugin for reprocessing uploaded entries with updated parsers and normalizers.

This `nomad` plugin was generated with `Cookiecutter` along with `@nomad`'s [`cookiecutter-nomad-plugin`](https://github.com/FAIRmat-NFDI/cookiecutter-nomad-plugin) template.

## Usage

The reprocessing action allows you to re-run parsers and normalizers on previously uploaded entries without re-uploading the raw data files. This is useful when:

- You fix bugs in a parser
- You add new normalization logic
- You update schema mappings
- You want to apply new metadata extraction to existing data

### Input Formats

The action accepts multiple upload IDs in two formats:

**1. Python List (JSON Array)** - Recommended for API/programmatic use:
```json
{
  "upload_id": "cD35rtcxTkGGS61Xo9KHxg",
  "upload_ids": [
    "abc123abc123abc123",
    "def456def456def456",
    "ghi789ghi789ghi789"
  ]
}
```

**2. Comma-Separated String** - Convenient for CLI/scripts:
```json
{
  "upload_id": "cD35rtcxTkGGS61Xo9KHxg",
  "upload_ids": "abc123abc123abc123, def456def456def456, ghi789ghi789ghi789"
}
```

Both formats are automatically handled by the plugin's input validation.

### Triggering via API

```bash
POST /api/v1/actions/reprocess_uploads/start
Content-Type: application/json

{
  "data": {
    "upload_id": "cD35rtcxTkGGS61Xo9KHxg",
    "upload_ids": ["upload_id_1", "upload_id_2", "upload_id_3"]
  }
}
```

### Triggering via GUI

Access the reprocessing action from the upload page action menu (if GUI integration is available).

### Architecture

The reprocessing action uses Temporal workflows to:
1. Spawns upload processing tasks sequentially on the CPU task queue
2. Poll each upload until processing completes
3. Generate a summary report with processing results

**Requirements:**
- NOMAD backend with Temporal workflow support (v1.4.1+)
- CPU worker running (`nomad admin run action-cpu-worker`)
- Docker services (Temporal, MongoDB, Elasticsearch)

## Inspecting logs in Kibana

The reprocessing summary is written per upload as `reprocessing_summary_<workflow_id>.json` in the context upload's files. For runs that stay below `summary_entry_threshold` total entries it contains the full per-entry logs; above that threshold the per-entry logs would make the file unmanageable, so the summary keeps only aggregate statistics and a Kibana pointer, and the individual logs are inspected in Kibana instead. This repository ships the pieces to make that log view available.

NOMAD forwards its structured logs to Elasticsearch through Logstash. Enable this in the deployment's `nomad.yaml` and restart the workers so they pick up the handler:

```yaml
logstash:
  enabled: true
  host: localhost
  tcp_port: '5000'
  level: INFO
```

Run a Logstash and a Kibana that match your Elasticsearch version on the same Docker network as the Elasticsearch service. Add them to your distro-dev `docker-compose.yaml`; the `logstash` service mounts the provided pipeline (`ops/logstash.conf`), which receives NOMAD's log stream on TCP port 5000 and writes it to a daily `nomad-logs-*` index:

```yaml
  logstash:
    image: docker.elastic.co/logstash/logstash:7.17.27
    container_name: nomad_logstash
    depends_on:
      - elastic
    environment:
      - XPACK_MONITORING_ENABLED=false
    ports:
      - '5000:5000'
    volumes:
      - ./nomad-reprocessing-plugin/ops/logstash.conf:/usr/share/logstash/pipeline/logstash.conf:ro

  kibana:
    image: docker.elastic.co/kibana/kibana:7.17.27
    container_name: nomad_kibana
    depends_on:
      - elastic
    environment:
      - ELASTICSEARCH_HOSTS=http://elastic:9200
    ports:
      - '5601:5601'
```

Adjust `elastic` to your Elasticsearch service name and the `ops/logstash.conf` path to wherever the plugin is checked out (override the Elasticsearch target with an `ES_HOSTS` environment variable on the `logstash` service if it is not reachable as `elastic:9200`). Then enable log shipping in `nomad.yaml` (above), bring the containers up (`docker-compose up -d logstash kibana`) and restart the workers.

Once Kibana is up, import the dashboard bundle `ops/kibana/nomad_dashboard.ndjson` once — from the UI (Stack Management → Saved Objects → Import) or with a single request:

```sh
curl -X POST 'http://localhost:5601/api/saved_objects/_import?overwrite=true' \
  -H 'kbn-xsrf: true' --form file=@ops/kibana/nomad_dashboard.ndjson
```

This creates the `nomad-logs-*` index pattern and the `NOMAD Reprocessing Errors` dashboard at `http://localhost:5601/app/dashboards#/view/nomad-reprocessing-errors` (optionally set `nomad-logs-*` as the default index pattern in Kibana's advanced settings). The dashboard breaks failures down by signature, parser, processing step, upload, entry and reprocessing workflow, groups distinct crashes by `exception_hash`, and includes a failures table with the diagnostic columns `level`, `event`, `digest`, `nomad.processing.step`, `nomad.processing.parser`, `nomad.entry_id`, `nomad.upload_id` and `nomad.processing.workflow_ids`. Scope any view to a single run with a `nomad.upload_id:"<id>"` query; the `digest` field gives the one-line cause of each failure and the `exception` field the full traceback. The `nomad.entry_id`, `nomad.upload_id` and `nomad.processing.workflow_ids` columns are rendered as links (via a URL field formatter on the index pattern) that open Discover filtered to that entry, upload or reprocessing workflow, so you can jump between an individual entry's logs or a whole reprocessing run quickly. The `nomad.processing.workflow_ids` field is provided by NOMAD's processing logs (nomad-lab); without it the reprocessing-workflow panel and column stay empty.

To make the entry column open the entry in a NOMAD v2 GUI instead, edit the URL field format on the index pattern (Stack Management → Data Views → `nomad-logs-*` → `nomad.entry_id` → Format: Url) with a template such as `<gui-base>/apps/<app>/{{value}}`, for example `http://localhost:3001/apps/entries/{{value}}`.

## Development

If you want to develop locally this plugin, clone the project and in the plugin folder, create a virtual environment (you can use Python 3.10, 3.11 or 3.12):
```sh
git clone https://github.com/FAIRmat-NFDI/nomad-reprocessing-plugin.git
cd nomad-reprocessing-plugin
python3.11 -m venv .pyenv
. .pyenv/bin/activate
```

Make sure to have `pip` upgraded:
```sh
pip install --upgrade pip
```

We recommend installing `uv` for fast pip installation of the packages:
```sh
pip install uv
```

Install the `nomad-lab` package:
```sh
uv pip install -e '.[dev]'
```

### Run the tests

You can run locally the tests:
```sh
python -m pytest -sv tests
```

where the `-s` and `-v` options toggle the output verbosity.

Our CI/CD pipeline produces a more comprehensive test report using the `pytest-cov` package. You can generate a local coverage report:
```sh
uv pip install pytest-cov
python -m pytest --cov=src tests
```

### Run linting and auto-formatting

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting the code. Ruff auto-formatting is also a part of the GitHub workflow actions. You can run locally:
```sh
ruff check .
ruff format . --check
```

### Debugging

For interactive debugging of the tests, use `pytest` with the `--pdb` flag. We recommend using an IDE for debugging, e.g., _VSCode_. If that is the case, add the following snippet to your `.vscode/launch.json`:
```json
{
  "configurations": [
      {
        "name": "<descriptive tag>",
        "type": "debugpy",
        "request": "launch",
        "cwd": "${workspaceFolder}",
        "program": "${workspaceFolder}/.pyenv/bin/pytest",
        "justMyCode": true,
        "env": {
            "_PYTEST_RAISE": "1"
        },
        "args": [
            "-sv",
            "--pdb",
            "<path-to-plugin-tests>",
        ]
    }
  ]
}
```

where `<path-to-plugin-tests>` must be changed to the local path to the test module to be debugged.

The settings configuration file `.vscode/settings.json` automatically applies the linting and formatting upon saving the modified file.

### Documentation on Github pages

To view the documentation locally, install the related packages using:
```sh
uv pip install -r requirements_docs.txt
```

Run the documentation server:
```sh
mkdocs serve
```

## Adding this plugin to NOMAD

Currently, NOMAD has two distinct flavors that are relevant depending on your role as an user:
1. [A NOMAD Oasis](#adding-this-plugin-in-your-nomad-oasis): any user with a NOMAD Oasis instance.
2. [Local NOMAD installation and the source code of NOMAD](#adding-this-plugin-in-your-local-nomad-installation-and-the-source-code-of-nomad): internal developers.

### Adding this plugin in your NOMAD Oasis

Read the [NOMAD plugin documentation](https://nomad-lab.eu/prod/v1/staging/docs/howto/oasis/plugins_install.html) for all details on how to deploy the plugin on your NOMAD instance.

### Adding this plugin in your local NOMAD installation and the source code of NOMAD

We now recommend using the dedicated [`nomad-distro-dev`](https://github.com/FAIRmat-NFDI/nomad-distro-dev) repository to simplify the process. Please refer to that repository for detailed instructions.

## Publish note
In the [GitHub actions workflow](./.github/workflows/publish.yml) for publishing the nomad-reprocessing-plugin plugin to PyPI, we commented out the `deploy` job . If you want to publish the plugin to `PyPI`, you need to set up your project in `PyPI`. There are several online tutorials on publishing a Python package to PyPI, e.g., [How to Publish a Python Package to PyPI](https://realpython.com/pypi-publish-python-package/). After that, you can uncomment the `deploy` job in the workflow file and push the changes to GitHub. The workflow will be triggered and the package will be published to `PyPI` when you create a new release on GitHub.

### Template update

We use [`cruft`](https://github.com/cruft/cruft) to update the project based on template changes. To run the check for updates locally, run `cruft update` in the root of the project. More details see the instructions on [`cruft` website](https://cruft.github.io/cruft/#updating-a-project).

## Main contributors
| Name | E-mail     |
|------|------------|
| Ahmed Ilyas | [ahmed.ilyas@physik.hu-berlin.de](mailto:ahmed.ilyas@physik.hu-berlin.de)
