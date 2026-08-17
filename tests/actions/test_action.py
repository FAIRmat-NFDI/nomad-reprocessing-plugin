import io
import json

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from nomad_reprocessing_plugin.actions.reprocess_uploads_action.activities import (
    build_reprocess_summary,
    reprocess_upload,
)
from nomad_reprocessing_plugin.actions.reprocess_uploads_action.models import (
    BuildReprocessSummaryInput,
    ReprocessSingleUploadInput,
    ReprocessUploadsWorkflowInput,
)
from nomad_reprocessing_plugin.actions.reprocess_uploads_action.workflows import (
    ReprocessUploadsWorkflow,
)

ACTIVITIES_MODULE = (
    'nomad_reprocessing_plugin.actions.reprocess_uploads_action.activities'
)


class FakeEntry:
    def __init__(
        self,
        entry_id: str,
        mainfile: str = '',
        parser_name: str = '',
        process_status: str = 'UNKNOWN',
    ):
        self.entry_id = entry_id
        self.mainfile = mainfile
        self.parser_name = parser_name
        self.process_status = process_status


class _StagingFiles:
    def __init__(self, sink: dict[str, str]):
        self._sink = sink

    def raw_file(self, path: str, _mode: str):
        sink = self._sink

        class _Ctx:
            def __enter__(self):
                self._buf = io.StringIO()
                return self._buf

            def __exit__(self, exc_type, _exc, _tb):
                if exc_type is None:
                    sink[path] = self._buf.getvalue()
                return False

        return _Ctx()


class _UploadFiles:
    def __init__(self, archive_logs: dict[str, list]):
        self._archive_logs = archive_logs

    def read_archive(self, entry_id: str):
        logs = self._archive_logs.get(entry_id, [])

        class _Ctx:
            def __enter__(self):
                return {entry_id: {'processing_logs': logs}}

            def __exit__(self, _exc_type, _exc, _tb):
                return False

        return _Ctx()


class FakeUpload:
    """Fake upload with ``n_entries`` entries, each carrying one INFO and one WARNING
    processing log."""

    def __init__(
        self,
        upload_id: str,
        n_entries: int = 1,
        process_status: str = 'SUCCESS',
        failed_entries_count: int = 0,
    ):
        self.upload_id = upload_id
        self.process_status = process_status
        self.total_entries_count = n_entries
        self.processed_entries_count = n_entries
        self.failed_entries_count = failed_entries_count
        self.written_files: dict[str, str] = {}
        self.staging_upload_files = _StagingFiles(self.written_files)
        self.process_calls: list[dict] = []

        self._entries = [
            FakeEntry(
                f'{upload_id}-e{i + 1}',
                mainfile=f'file_{i + 1}.out',
                parser_name='fake_parser',
                process_status='SUCCESS',
            )
            for i in range(n_entries)
        ]
        archive_logs = {
            entry.entry_id: [
                {'level': 'INFO', 'event': 'start', 'timestamp': 't0'},
                {'level': 'WARNING', 'event': 'watch out', 'timestamp': 't1'},
            ]
            for entry in self._entries
        }
        self.upload_files = _UploadFiles(archive_logs)

    def entries_sublist(self, start: int, end: int):
        return self._entries[start:end]

    def process_upload(self, **kwargs):
        self.process_calls.append(kwargs)
        return object()


def _fake_upload_api(uploads: dict[str, FakeUpload]):
    class FakeUploadAPI:
        @staticmethod
        def get(upload_id: str) -> FakeUpload:
            return uploads.setdefault(upload_id, FakeUpload(upload_id))

    return FakeUploadAPI


def _patch_summary_config(monkeypatch, threshold: int, kibana_base_url: str = ''):
    monkeypatch.setattr(
        f'{ACTIVITIES_MODULE}._get_summary_config',
        lambda: (threshold, kibana_base_url),
    )


def _patch_summary_upload(monkeypatch, upload: 'FakeUpload'):
    """Route the summary to a dedicated upload, bypassing Mongo/file-store lookup."""
    monkeypatch.setattr(
        f'{ACTIVITIES_MODULE}._get_or_create_summary_upload',
        lambda user_id: upload,
    )


@pytest.mark.asyncio
async def test_reprocess_upload_activity_polls_until_processed(monkeypatch):
    states = ['RUNNING', 'RUNNING', 'SUCCESS']
    state_index = {'value': 0}

    class FakeUploadAPI:
        @staticmethod
        def get(upload_id: str):
            index = min(state_index['value'], len(states) - 1)
            upload = FakeUpload(upload_id, process_status=states[index])
            state_index['value'] += 1
            return upload

    sleep_calls: list[int] = []

    async def fake_sleep(seconds: int):
        sleep_calls.append(seconds)

    monkeypatch.setattr(f'{ACTIVITIES_MODULE}.Upload', FakeUploadAPI)
    monkeypatch.setattr(f'{ACTIVITIES_MODULE}.asyncio.sleep', fake_sleep)

    result = await reprocess_upload(ReprocessSingleUploadInput(upload_id='u1'))

    assert result is None
    assert sleep_calls == [5, 5]


@pytest.mark.asyncio
async def test_build_reprocess_summary_full_mode(monkeypatch):
    """Below the threshold the summary holds full per-entry metadata and logs."""
    uploads: dict[str, FakeUpload] = {}
    monkeypatch.setattr(f'{ACTIVITIES_MODULE}.Upload', _fake_upload_api(uploads))
    summary_upload = FakeUpload('reprocessing-upload', n_entries=0)
    _patch_summary_upload(monkeypatch, summary_upload)
    _patch_summary_config(monkeypatch, threshold=200)

    result = await build_reprocess_summary(
        BuildReprocessSummaryInput(
            user_id='user-1', workflow_id='wf-123', upload_ids=['u1']
        )
    )

    assert result == {
        'summary_upload_id': 'reprocessing-upload',
        'summary_file': 'reprocessing_summary_wf-123.json',
        'summary_entry_mainfile': 'reprocessing_summary_wf-123.archive.json',
        'uploads': [
            {
                'upload_id': 'u1',
                'status': 'SUCCESS',
                'entry_status': '1 success, 0 failures',
            }
        ],
    }
    # searchable summary entry: metadata records which uploads the run touched,
    # and the archive file is processed so the entry gets indexed.
    entry_meta = json.loads(
        summary_upload.written_files['reprocessing_summary_wf-123.archive.json']
    )['metadata']
    assert entry_meta['entry_name'] == 'Reprocessing wf-123'
    assert entry_meta['references'] == ['u1']
    assert 'reprocessing_summary_wf-123.json' in entry_meta['comment']
    assert summary_upload.process_calls == [
        {'path_filter': 'reprocessing_summary_wf-123.archive.json'}
    ]
    written = summary_upload.written_files['reprocessing_summary_wf-123.json']
    payload = json.loads(written)
    assert payload['mode'] == 'full'
    assert payload['total_entries'] == 1
    assert payload['uploads'] == {
        'u1': {
            'status': 'SUCCESS',
            'stats': {
                'total_entries': 1,
                'successful': 1,
                'failed': 0,
                'total_errors': 0,
                'total_warnings': 1,
                'total_info': 1,
                'total_debug': 0,
                'total_critical': 0,
            },
            'entries': [
                {
                    'entry_id': 'u1-e1',
                    'mainfile': 'file_1.out',
                    'parser': 'fake_parser',
                    'status': 'SUCCESS',
                    'log_stats': {
                        'ERROR': 0,
                        'WARNING': 1,
                        'INFO': 1,
                        'DEBUG': 0,
                        'CRITICAL': 0,
                    },
                    'high_priority_logs': [
                        {
                            'level': 'WARNING',
                            'event': 'watch out',
                            'entry_id': 'u1-e1',
                            'index': 1,
                            'timestamp': 't1',
                        }
                    ],
                    'processing_errors': [],
                    'logs': [
                        {'level': 'INFO', 'event': 'start', 'timestamp': 't0'},
                        {'level': 'WARNING', 'event': 'watch out', 'timestamp': 't1'},
                    ],
                }
            ],
        }
    }


@pytest.mark.asyncio
async def test_build_reprocess_summary_kibana_mode(monkeypatch):
    """Above the threshold the summary drops per-entry logs and points to Kibana."""
    n_entries = 5
    uploads: dict[str, FakeUpload] = {'big': FakeUpload('big', n_entries=n_entries)}
    monkeypatch.setattr(f'{ACTIVITIES_MODULE}.Upload', _fake_upload_api(uploads))
    summary_upload = FakeUpload('reprocessing-upload', n_entries=0)
    _patch_summary_upload(monkeypatch, summary_upload)
    _patch_summary_config(
        monkeypatch, threshold=3, kibana_base_url='http://localhost:5601/'
    )

    await build_reprocess_summary(
        BuildReprocessSummaryInput(
            user_id='user-1', workflow_id='wf-xl', upload_ids=['big']
        )
    )

    written = summary_upload.written_files['reprocessing_summary_wf-xl.json']
    payload = json.loads(written)
    assert payload['mode'] == 'kibana'
    assert payload['total_entries'] == n_entries

    big = payload['uploads']['big']
    assert 'entries' not in big  # per-entry logs are deferred to Kibana
    assert big['stats'] == {
        'total_entries': n_entries,
        'successful': n_entries,
        'failed': 0,
        'total_errors': 0,
        'total_warnings': n_entries,
        'total_info': n_entries,
        'total_debug': 0,
        'total_critical': 0,
    }
    assert big['kibana']['index'] == 'nomad-logs-*'
    assert big['kibana']['query'] == 'nomad.upload_id:"big"'
    assert big['kibana']['workflow_id'] == 'wf-xl'
    assert big['kibana']['url'].startswith('http://localhost:5601/app/discover#/?_a=')


@pytest.mark.parametrize(
    'threshold, expected_mode',
    [
        pytest.param(200, 'full', id='below-threshold-full'),
        pytest.param(4, 'full', id='at-threshold-full'),
        pytest.param(3, 'kibana', id='above-threshold-kibana'),
        pytest.param(0, 'kibana', id='zero-threshold-kibana'),
    ],
)
@pytest.mark.asyncio
async def test_build_reprocess_summary_mode_threshold(
    monkeypatch, threshold, expected_mode
):
    """Two uploads with two entries each (4 total) switch mode around the threshold."""
    uploads: dict[str, FakeUpload] = {
        'u1': FakeUpload('u1', n_entries=2),
        'u2': FakeUpload('u2', n_entries=2),
    }
    monkeypatch.setattr(f'{ACTIVITIES_MODULE}.Upload', _fake_upload_api(uploads))
    summary_upload = FakeUpload('reprocessing-upload', n_entries=0)
    _patch_summary_upload(monkeypatch, summary_upload)
    _patch_summary_config(monkeypatch, threshold=threshold)
    expected_total = sum(upload.total_entries_count for upload in uploads.values())

    await build_reprocess_summary(
        BuildReprocessSummaryInput(
            user_id='user-1', workflow_id='wf', upload_ids=['u1', 'u2']
        )
    )

    payload = json.loads(summary_upload.written_files['reprocessing_summary_wf.json'])
    assert payload['mode'] == expected_mode
    assert payload['total_entries'] == expected_total
    has_entries = 'entries' in payload['uploads']['u1']
    assert has_entries is (expected_mode == 'full')

    # regardless of mode, a searchable entry referencing both uploads is written
    # and processed
    entry_meta = json.loads(
        summary_upload.written_files['reprocessing_summary_wf.archive.json']
    )['metadata']
    assert entry_meta['references'] == ['u1', 'u2']
    assert summary_upload.process_calls == [
        {'path_filter': 'reprocessing_summary_wf.archive.json'}
    ]


@pytest.mark.asyncio
async def test_build_reprocess_summary_missing_archive(monkeypatch):
    """An unreadable archive yields zeroed log stats rather than raising."""

    class BrokenUpload(FakeUpload):
        def __init__(self, upload_id: str):
            super().__init__(upload_id, n_entries=1)

            class _Broken:
                def read_archive(self, entry_id: str):
                    raise KeyError(entry_id)

            self.upload_files = _Broken()

    uploads = {'u1': BrokenUpload('u1')}
    monkeypatch.setattr(f'{ACTIVITIES_MODULE}.Upload', _fake_upload_api(uploads))
    summary_upload = FakeUpload('reprocessing-upload', n_entries=0)
    _patch_summary_upload(monkeypatch, summary_upload)
    _patch_summary_config(monkeypatch, threshold=200)

    await build_reprocess_summary(
        BuildReprocessSummaryInput(
            user_id='user-1', workflow_id='wf', upload_ids=['u1']
        )
    )

    payload = json.loads(summary_upload.written_files['reprocessing_summary_wf.json'])
    entry = payload['uploads']['u1']['entries'][0]
    assert entry['logs'] == []
    assert entry['log_stats'] == {
        'ERROR': 0,
        'WARNING': 0,
        'INFO': 0,
        'DEBUG': 0,
        'CRITICAL': 0,
    }


@pytest.mark.asyncio
async def test_reprocess_uploads_workflow(monkeypatch):
    upload_states = {
        'u1': ['RUNNING', 'SUCCESS'],
        'u2': ['RUNNING', 'RUNNING', 'SUCCESS'],
    }
    upload_indices = {'u1': 0, 'u2': 0}

    class FakeUploadAPI:
        @staticmethod
        def get(upload_id: str):
            if upload_id not in upload_states:
                return FakeUpload(upload_id, n_entries=2)
            states = upload_states[upload_id]
            index = min(upload_indices[upload_id], len(states) - 1)
            state = states[index]
            upload_indices[upload_id] += 1
            return FakeUpload(upload_id, n_entries=2, process_status=state)

    async def fake_sleep(_seconds: int):
        return None

    monkeypatch.setattr(f'{ACTIVITIES_MODULE}.Upload', FakeUploadAPI)
    monkeypatch.setattr(f'{ACTIVITIES_MODULE}.asyncio.sleep', fake_sleep)
    _patch_summary_upload(monkeypatch, FakeUpload('reprocessing-upload', n_entries=0))
    _patch_summary_config(monkeypatch, threshold=200)

    task_queue = 'test-reprocess-uploads-workflow'
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ReprocessUploadsWorkflow],
            activities=[reprocess_upload, build_reprocess_summary],
        ):
            result = await env.client.execute_workflow(
                ReprocessUploadsWorkflow.run,
                ReprocessUploadsWorkflowInput(
                    user_id='user-id',
                    target_upload_ids=['u1', 'u2'],
                ),
                id='test-workflow',
                task_queue=task_queue,
            )
            assert result == {
                'summary_upload_id': 'reprocessing-upload',
                'summary_file': 'reprocessing_summary_test-workflow.json',
                'summary_entry_mainfile': (
                    'reprocessing_summary_test-workflow.archive.json'
                ),
                'uploads': [
                    {
                        'upload_id': 'u1',
                        'status': 'SUCCESS',
                        'entry_status': '2 success, 0 failures',
                    },
                    {
                        'upload_id': 'u2',
                        'status': 'SUCCESS',
                        'entry_status': '2 success, 0 failures',
                    },
                ],
            }
