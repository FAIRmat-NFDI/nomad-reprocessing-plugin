import pytest

from nomad_reprocessing_plugin.actions.reprocess_uploads_action.models import (
    BuildReprocessSummaryInput,
    ReprocessUploadsWorkflowInput,
)


class TestReprocessUploadsWorkflowInput:
    """Test input validation for ReprocessUploadsWorkflowInput model."""

    def test_upload_ids_as_list(self):
        """Test that upload_ids accepts a Python list."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids=['upload1', 'upload2', 'upload3'],
        )

        assert input_data.target_upload_ids == ['upload1', 'upload2', 'upload3']

    def test_upload_ids_as_comma_separated_string(self):
        """Test that upload_ids accepts comma-separated string."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids='upload1, upload2, upload3',
        )

        assert input_data.target_upload_ids == ['upload1', 'upload2', 'upload3']

    def test_upload_ids_comma_separated_no_spaces(self):
        """Test comma-separated string without spaces."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids='upload1,upload2,upload3',
        )

        assert input_data.target_upload_ids == ['upload1', 'upload2', 'upload3']

    def test_upload_ids_comma_separated_mixed_spacing(self):
        """Test comma-separated string with irregular spacing."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids='  upload1  ,upload2,  upload3  ',
        )

        assert input_data.target_upload_ids == ['upload1', 'upload2', 'upload3']

    def test_upload_ids_single_item_as_string(self):
        """Test single upload ID as string (no commas)."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids='single-upload-id',
        )

        assert input_data.target_upload_ids == ['single-upload-id']

    def test_upload_ids_empty_string_filtered(self):
        """Test that empty strings from splitting are filtered out."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids='upload1,,,upload2',
        )

        assert input_data.target_upload_ids == ['upload1', 'upload2']

    def test_upload_ids_realistic_format(self):
        """Test with realistic base64url-encoded upload IDs."""
        realistic_ids = (
            'cD35rtcxTkGGS61Xo9KHxg, JaYmVdy9R-G8KdgkXYYz-w, abc123def456xyz789'
        )
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids=realistic_ids,
        )

        expected = [
            'cD35rtcxTkGGS61Xo9KHxg',
            'JaYmVdy9R-G8KdgkXYYz-w',
            'abc123def456xyz789',
        ]
        assert input_data.target_upload_ids == expected

    def test_upload_ids_list_with_trailing_commas(self):
        """Test list containing strings with trailing commas (bug fix)."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids=['VP4vZt43TaOV2yxYA0DEGQ,,,,'],
        )

        assert input_data.target_upload_ids == ['VP4vZt43TaOV2yxYA0DEGQ']

    def test_upload_ids_list_with_embedded_commas(self):
        """Test list where items contain multiple comma-separated IDs."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids=['id1,id2', 'id3,id4,id5'],
        )

        assert input_data.target_upload_ids == ['id1', 'id2', 'id3', 'id4', 'id5']

    def test_upload_ids_list_with_preceding_commas(self):
        """Test list with items containing preceding commas."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids=[',,,,VP4vZt43TaOV2yxYA0DEGQ'],
        )

        assert input_data.target_upload_ids == ['VP4vZt43TaOV2yxYA0DEGQ']

    def test_upload_ids_string_with_preceding_and_trailing_commas(self):
        """Test string with both preceding and trailing commas."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids=',,id1,,,id2,,',
        )

        assert input_data.target_upload_ids == ['id1', 'id2']

    def test_upload_ids_list_with_empty_strings(self):
        """Test list with empty strings (e.g., from GUI errors)."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids=['id1', '', 'id2', '   ', 'id3'],
        )

        assert input_data.target_upload_ids == ['id1', 'id2', 'id3']

    def test_upload_ids_list_with_only_empty_strings(self):
        """Test list containing only empty/whitespace strings."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids=['', '  ', '   '],
        )

        assert input_data.target_upload_ids == []

    @pytest.mark.parametrize(
        'kwargs, expected_upload_id',
        [
            pytest.param({}, None, id='omitted-defaults-none'),
            pytest.param(
                {'upload_id': 'context-upload'}, 'context-upload', id='provided'
            ),
        ],
    )
    def test_upload_id_optional_context(self, kwargs, expected_upload_id):
        """upload_id is optional context: None when omitted, kept when provided."""
        input_data = ReprocessUploadsWorkflowInput(
            user_id='test-user-id',
            target_upload_ids=['upload1'],
            **kwargs,
        )

        assert input_data.upload_id == expected_upload_id

    def test_schema_upload_id_optional_and_visible(self):
        """upload_id is optional (not required) and not hidden; targets required."""
        schema = ReprocessUploadsWorkflowInput.model_json_schema()
        props = schema['properties']
        assert 'upload_id' in props
        assert 'hidden' not in props['upload_id']
        required = schema.get('required', [])
        assert 'upload_id' not in required
        assert 'target_upload_ids' in required


class TestBuildReprocessSummaryInput:
    """Test input validation for BuildReprocessSummaryInput model."""

    def test_upload_ids_as_list(self):
        """Test that upload_ids accepts a Python list."""
        input_data = BuildReprocessSummaryInput(
            user_id='test-user-id',
            workflow_id='workflow-123',
            upload_ids=['upload1', 'upload2'],
        )

        assert input_data.upload_ids == ['upload1', 'upload2']

    def test_upload_ids_as_comma_separated_string(self):
        """Test that upload_ids accepts comma-separated string."""
        input_data = BuildReprocessSummaryInput(
            user_id='test-user-id',
            workflow_id='workflow-123',
            upload_ids='upload1, upload2',
        )

        assert input_data.upload_ids == ['upload1', 'upload2']

    def test_upload_ids_single_item(self):
        """Test single upload ID as string."""
        input_data = BuildReprocessSummaryInput(
            user_id='test-user-id',
            workflow_id='workflow-123',
            upload_ids='single-upload',
        )

        assert input_data.upload_ids == ['single-upload']
