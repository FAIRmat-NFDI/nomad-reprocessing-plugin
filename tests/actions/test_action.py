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


@pytest.mark.asyncio
async def test_reprocess_upload_activity_polls_until_processed(monkeypatch):
    class FakeUpload:
        def __init__(self, upload_id: str, process_status: str, idx: int):
            self.upload_id = upload_id
            self.process_status = process_status
            self.processed_entries_count = idx
            self.total_entries_count = 3
            self.failed_entries_count = 1

        def process_upload(self):
            return object()

    states = ['RUNNING', 'RUNNING', 'SUCCESS']
    state_index = {'value': 0}

    class FakeUploadAPI:
        @staticmethod
        def get(upload_id: str):
            index = min(state_index['value'], len(states) - 1)
            state = states[index]
            state_index['value'] += 1
            return FakeUpload(upload_id, state, state_index['value'])

    sleep_calls: list[int] = []

    async def fake_sleep(seconds: int):
        sleep_calls.append(seconds)

    monkeypatch.setattr(
        'nomad_reprocessing_plugin.actions.reprocess_uploads_action.activities.Upload',
        FakeUploadAPI,
    )
    monkeypatch.setattr(
        'nomad_reprocessing_plugin.actions.reprocess_uploads_action.activities.asyncio.sleep',
        fake_sleep,
    )

    result = await reprocess_upload(ReprocessSingleUploadInput(upload_id='u1'))

    assert result is None
    assert sleep_calls == [5, 5]


@pytest.mark.asyncio
async def test_build_reprocess_summary_activity(monkeypatch):
    class FakeEntry:
        def __init__(self, entry_id: str):
            self.entry_id = entry_id

    class FakeUpload:
        def __init__(self, upload_id: str):
            self.upload_id = upload_id
            self.process_status = 'SUCCESS'
            self.total_entries_count = 2
            self.processed_entries_count = 2
            self.failed_entries_count = 0
            self._written_files: dict[str, str] = {}

            class _StagingFiles:
                def __init__(self, outer):
                    self._outer = outer

                def raw_file(self, path: str, _mode: str):
                    outer = self._outer

                    class _Ctx:
                        def __enter__(self):
                            self._buf = io.StringIO()
                            return self._buf

                        def __exit__(self, exc_type, exc, _tb):
                            if exc_type is None:
                                outer._written_files[path] = self._buf.getvalue()
                            return False

                    return _Ctx()

            self.staging_upload_files = _StagingFiles(self)
            self._archive_logs = {
                f'{self.upload_id}-e1': [f'{self.upload_id}-entry-log'],
            }

            class _UploadFiles:
                def __init__(self, outer):
                    self._outer = outer

                def read_archive(self, entry_id: str):
                    outer = self._outer

                    class _Ctx:
                        def __enter__(self):
                            return {
                                entry_id: {
                                    'processing_logs': outer._archive_logs.get(
                                        entry_id, []
                                    )
                                }
                            }

                        def __exit__(self, _exc_type, _exc, _tb):
                            return False

                    return _Ctx()

            self.upload_files = _UploadFiles(self)

        def entries_sublist(self, _start: int, _end: int):
            return [FakeEntry(f'{self.upload_id}-e1')]

    uploads: dict[str, FakeUpload] = {}

    class FakeUploadAPI:
        @staticmethod
        def get(upload_id: str):
            if upload_id not in uploads:
                uploads[upload_id] = FakeUpload(upload_id)
            return uploads[upload_id]

    monkeypatch.setattr(
        'nomad_reprocessing_plugin.actions.reprocess_uploads_action.activities.Upload',
        FakeUploadAPI,
    )

    result = await build_reprocess_summary(
        BuildReprocessSummaryInput(
            upload_id='summary-upload',
            workflow_id='wf-123',
            upload_ids=['u1', 'u2'],
        )
    )

    assert result == {
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
        ]
    }
    summary_filename = 'reprocessing_summary_wf-123.json'
    assert summary_filename in uploads['summary-upload']._written_files
    assert json.loads(
        uploads['summary-upload']._written_files[summary_filename]
    ) == {
        'u1': {
            'status': 'SUCCESS',
            'stats': {
                'total_entries': 2,
                'successful': 2,
                'failed': 0,
                'total_errors': 0,
                'total_warnings': 0,
                'total_info': 1,
                'total_debug': 0,
                'total_critical': 0,
            },
            'entries': [
                {
                    'entry_id': 'u1-e1',
                    'mainfile': '',
                    'parser': '',
                    'status': 'UNKNOWN',
                    'log_stats': {
                        'ERROR': 0,
                        'WARNING': 0,
                        'INFO': 1,
                        'DEBUG': 0,
                        'CRITICAL': 0,
                    },
                    'processing_errors': [],
                    'logs': ['u1-entry-log'],
                },
            ],
        },
        'u2': {
            'status': 'SUCCESS',
            'stats': {
                'total_entries': 2,
                'successful': 2,
                'failed': 0,
                'total_errors': 0,
                'total_warnings': 0,
                'total_info': 1,
                'total_debug': 0,
                'total_critical': 0,
            },
            'entries': [
                {
                    'entry_id': 'u2-e1',
                    'mainfile': '',
                    'parser': '',
                    'status': 'UNKNOWN',
                    'log_stats': {
                        'ERROR': 0,
                        'WARNING': 0,
                        'INFO': 1,
                        'DEBUG': 0,
                        'CRITICAL': 0,
                    },
                    'processing_errors': [],
                    'logs': ['u2-entry-log'],
                },
            ],
        },
    }


@pytest.mark.asyncio
async def test_reprocess_uploads_workflow(monkeypatch):
    class FakeEntry:
        def __init__(self, entry_id: str):
            self.entry_id = entry_id

    class FakeUpload:
        def __init__(self, upload_id: str, process_status: str, idx: int):
            self.upload_id = upload_id
            self.process_status = process_status
            self.processed_entries_count = idx
            self.total_entries_count = 2
            self.failed_entries_count = 0

            class _StagingFiles:
                def raw_file(self, _path: str, _mode: str):
                    class _Ctx:
                        def __enter__(self):
                            return io.StringIO()

                        def __exit__(self, _exc_type, _exc, _tb):
                            return False

                    return _Ctx()

            self.staging_upload_files = _StagingFiles()
            self._archive_logs = {
                f'{self.upload_id}-e1': [f'{self.upload_id}-entry-log'],
            }

            class _UploadFiles:
                def __init__(self, outer):
                    self._outer = outer

                def read_archive(self, entry_id: str):
                    outer = self._outer

                    class _Ctx:
                        def __enter__(self):
                            return {
                                entry_id: {
                                    'processing_logs': outer._archive_logs.get(
                                        entry_id, []
                                    )
                                }
                            }

                        def __exit__(self, _exc_type, _exc, _tb):
                            return False

                    return _Ctx()

            self.upload_files = _UploadFiles(self)

        def process_upload(self):
            return object()

        def entries_sublist(self, _start: int, _end: int):
            return [FakeEntry(f'{self.upload_id}-e1')]

    upload_states = {
        'u1': ['RUNNING', 'SUCCESS'],
        'u2': ['RUNNING', 'RUNNING', 'SUCCESS'],
    }
    upload_indices = {'u1': 0, 'u2': 0}

    class FakeUploadAPI:
        @staticmethod
        def get(upload_id: str):
            if upload_id not in upload_states:
                return FakeUpload(upload_id, 'SUCCESS', 2)
            states = upload_states[upload_id]
            index = min(upload_indices[upload_id], len(states) - 1)
            state = states[index]
            upload_indices[upload_id] += 1
            return FakeUpload(upload_id, state, upload_indices[upload_id])

    async def fake_sleep(_seconds: int):
        return None

    monkeypatch.setattr(
        'nomad_reprocessing_plugin.actions.reprocess_uploads_action.activities.Upload',
        FakeUploadAPI,
    )
    monkeypatch.setattr(
        'nomad_reprocessing_plugin.actions.reprocess_uploads_action.activities.asyncio.sleep',
        fake_sleep,
    )

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
                    upload_id='context-upload',
                    user_id='user-id',
                    upload_ids=['u1', 'u2'],
                ),
                id='test-workflow',
                task_queue=task_queue,
            )
            assert result == {
                'uploads': [
                    {
                        'upload_id': 'u1',
                        'status': 'SUCCESS',
                        'entry_status': '3 success, 0 failures',
                    },
                    {
                        'upload_id': 'u2',
                        'status': 'SUCCESS',
                        'entry_status': '4 success, 0 failures',
                    },
                ]
            }
