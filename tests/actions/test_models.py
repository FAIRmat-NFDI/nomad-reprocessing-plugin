import pytest
from pydantic import ValidationError

from nomad_reprocessing_plugin.actions.reprocess_uploads_action.models import (
    BuildReprocessSummaryInput,
    ReprocessUploadsWorkflowInput,
)


class TestReprocessUploadsWorkflowInput:
    """Test input validation for ReprocessUploadsWorkflowInput model."""

    def test_upload_ids_as_list(self):
        """Test that upload_ids accepts a Python list."""
        input_data = ReprocessUploadsWorkflowInput(
            upload_id='context-upload-id',
            user_id='test-user-id',
            upload_ids=['upload1', 'upload2', 'upload3'],
        )

        assert input_data.upload_ids == ['upload1', 'upload2', 'upload3']

    def test_upload_ids_as_comma_separated_string(self):
        """Test that upload_ids accepts comma-separated string."""
        input_data = ReprocessUploadsWorkflowInput(
            upload_id='context-upload-id',
            user_id='test-user-id',
            upload_ids='upload1, upload2, upload3',
        )

        assert input_data.upload_ids == ['upload1', 'upload2', 'upload3']

    def test_upload_ids_comma_separated_no_spaces(self):
        """Test comma-separated string without spaces."""
        input_data = ReprocessUploadsWorkflowInput(
            upload_id='context-upload-id',
            user_id='test-user-id',
            upload_ids='upload1,upload2,upload3',
        )

        assert input_data.upload_ids == ['upload1', 'upload2', 'upload3']

    def test_upload_ids_comma_separated_mixed_spacing(self):
        """Test comma-separated string with irregular spacing."""
        input_data = ReprocessUploadsWorkflowInput(
            upload_id='context-upload-id',
            user_id='test-user-id',
            upload_ids='  upload1  ,upload2,  upload3  ',
        )

        assert input_data.upload_ids == ['upload1', 'upload2', 'upload3']

    def test_upload_ids_single_item_as_string(self):
        """Test single upload ID as string (no commas)."""
        input_data = ReprocessUploadsWorkflowInput(
            upload_id='context-upload-id',
            user_id='test-user-id',
            upload_ids='single-upload-id',
        )

        assert input_data.upload_ids == ['single-upload-id']

    def test_upload_ids_empty_string_filtered(self):
        """Test that empty strings from splitting are filtered out."""
        input_data = ReprocessUploadsWorkflowInput(
            upload_id='context-upload-id',
            user_id='test-user-id',
            upload_ids='upload1,,,upload2',
        )

        assert input_data.upload_ids == ['upload1', 'upload2']

    def test_upload_ids_realistic_format(self):
        """Test with realistic base64url-encoded upload IDs."""
        realistic_ids = 'cD35rtcxTkGGS61Xo9KHxg, JaYmVdy9R-G8KdgkXYYz-w, abc123def456xyz789'
        input_data = ReprocessUploadsWorkflowInput(
            upload_id='context-upload-id',
            user_id='test-user-id',
            upload_ids=realistic_ids,
        )

        expected = [
            'cD35rtcxTkGGS61Xo9KHxg',
            'JaYmVdy9R-G8KdgkXYYz-w',
            'abc123def456xyz789',
        ]
        assert input_data.upload_ids == expected


class TestBuildReprocessSummaryInput:
    """Test input validation for BuildReprocessSummaryInput model."""

    def test_upload_ids_as_list(self):
        """Test that upload_ids accepts a Python list."""
        input_data = BuildReprocessSummaryInput(
            upload_id='summary-upload-id',
            workflow_id='workflow-123',
            upload_ids=['upload1', 'upload2'],
        )

        assert input_data.upload_ids == ['upload1', 'upload2']

    def test_upload_ids_as_comma_separated_string(self):
        """Test that upload_ids accepts comma-separated string."""
        input_data = BuildReprocessSummaryInput(
            upload_id='summary-upload-id',
            workflow_id='workflow-123',
            upload_ids='upload1, upload2',
        )

        assert input_data.upload_ids == ['upload1', 'upload2']

    def test_upload_ids_single_item(self):
        """Test single upload ID as string."""
        input_data = BuildReprocessSummaryInput(
            upload_id='summary-upload-id',
            workflow_id='workflow-123',
            upload_ids='single-upload',
        )

        assert input_data.upload_ids == ['single-upload']
