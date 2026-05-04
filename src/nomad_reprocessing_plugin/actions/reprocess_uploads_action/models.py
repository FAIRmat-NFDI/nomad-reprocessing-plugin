from pydantic import BaseModel, Field


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
        ..., description='List of upload identifiers to reprocess one by one.'
    )


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
        ..., description='List of upload identifiers that were reprocessed.'
    )
