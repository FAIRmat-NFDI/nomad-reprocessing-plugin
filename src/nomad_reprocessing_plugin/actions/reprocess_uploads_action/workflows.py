from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nomad_reprocessing_plugin.actions.reprocess_uploads_action.activities import (
        build_reprocess_summary,
        reprocess_upload,
    )
    from nomad_reprocessing_plugin.actions.reprocess_uploads_action.models import (
        BuildReprocessSummaryInput,
        ReprocessSingleUploadInput,
        ReprocessUploadsWorkflowInput,
    )


@workflow.defn
class ReprocessUploadsWorkflow:
    @workflow.run
    async def run(self, data: ReprocessUploadsWorkflowInput) -> dict:
        retry_policy = RetryPolicy(
            maximum_attempts=3,
        )

        for upload_id in data.upload_ids:
            await workflow.execute_activity(
                reprocess_upload,
                ReprocessSingleUploadInput(upload_id=upload_id),
                start_to_close_timeout=timedelta(hours=24),
                retry_policy=retry_policy,
            )

        summary = await workflow.execute_activity(
            build_reprocess_summary,
            BuildReprocessSummaryInput(
                upload_id=data.upload_id,
                workflow_id=workflow.info().workflow_id,
                upload_ids=data.upload_ids,
            ),
            start_to_close_timeout=timedelta(hours=24),
            retry_policy=retry_policy,
        )
        return summary
