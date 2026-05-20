from pydantic import BaseModel, Field, field_validator


def parse_upload_id_list(value: str | list[str]) -> list[str]:
    """Parse upload IDs from either a Python list or comma-separated string.

    Args:
        value: Either a list of upload IDs or a comma-separated string

    Returns:
        List of upload ID strings with whitespace trimmed and empty strings filtered

    Examples:
        >>> parse_upload_id_list(['id1', 'id2'])
        ['id1', 'id2']
        >>> parse_upload_id_list('id1, id2, id3')
        ['id1', 'id2', 'id3']
        >>> parse_upload_id_list('id1,,,id2')
        ['id1', 'id2']
        >>> parse_upload_id_list(['id1,,,,'])
        ['id1']
    """
    if isinstance(value, str):
        # Split comma-separated string and filter empty items
        return [upload_id.strip() for upload_id in value.split(',') if upload_id.strip()]

    # Handle list case - each item might also contain commas
    result = []
    for item in value:
        if isinstance(item, str):
            # Split each string item by comma in case it contains multiple IDs
            result.extend([upload_id.strip() for upload_id in item.split(',') if upload_id.strip()])
        else:
            # Non-string items - just include them as-is (should not happen, but be safe)
            result.append(item)

    return result


class ReprocessUploadsWorkflowInput(BaseModel):
    """Input model for reprocessing multiple uploads."""

    upload_id: str = Field(
        ...,
        description='Unique identifier for the upload associated with the workflow context.',
    )
    user_id: str = Field(
        ..., description='Unique identifier for the user who initiated the workflow.'
    )
    upload_ids: list[str] = Field(
        ...,
        description='List of upload identifiers to reprocess one by one. Can be provided as a Python list or comma-separated string.',
    )

    @field_validator('upload_ids', mode='before')
    @classmethod
    def validate_upload_ids(cls, v):
        """Parse upload_ids from either list or comma-separated string."""
        return parse_upload_id_list(v)


class ReprocessSingleUploadInput(BaseModel):
    """Input model for reprocessing a single upload."""

    upload_id: str = Field(..., description='Unique identifier for the upload.')


class BuildReprocessSummaryInput(BaseModel):
    """Input model for building the reprocessing summary payload."""

    upload_id: str = Field(
        ...,
        description='Upload identifier where the generated summary payload is persisted.',
    )
    workflow_id: str = Field(
        ..., description='Workflow identifier used to name the summary JSON file.'
    )
    upload_ids: list[str] = Field(
        ...,
        description='List of upload identifiers that were reprocessed. Can be provided as a Python list or comma-separated string.',
    )

    @field_validator('upload_ids', mode='before')
    @classmethod
    def validate_upload_ids(cls, v):
        """Parse upload_ids from either list or comma-separated string."""
        return parse_upload_id_list(v)
