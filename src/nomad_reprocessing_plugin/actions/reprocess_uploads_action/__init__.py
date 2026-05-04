from nomad.actions import TaskQueue
from pydantic import Field
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from nomad.config.models.plugins import ActionEntryPoint


class ReprocessUploadsActionEntryPoint(ActionEntryPoint):
    task_queue: str = Field(
        default=TaskQueue.CPU, description='Determines the task queue for this action'
    )

    def load(self):
        from nomad.actions import Action

        from nomad_reprocessing_plugin.actions.reprocess_uploads_action.activities import (
            build_reprocess_summary,
            reprocess_upload,
        )
        from nomad_reprocessing_plugin.actions.reprocess_uploads_action.workflows import (
            ReprocessUploadsWorkflow,
        )

        return Action(
            task_queue=self.task_queue,
            workflow=ReprocessUploadsWorkflow,
            activities=[reprocess_upload, build_reprocess_summary],
        )


reprocess_uploads_action_entry_point = ReprocessUploadsActionEntryPoint(
    name='ReprocessUploadsAction',
    description='Reprocess a list of uploads sequentially.',
)
