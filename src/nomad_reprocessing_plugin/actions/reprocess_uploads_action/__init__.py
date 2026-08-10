from nomad.actions import TaskQueue
from pydantic import Field
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from nomad.config.models.plugins import ActionEntryPoint


class ReprocessUploadsActionEntryPoint(ActionEntryPoint):
    task_queue: str = Field(
        default=TaskQueue.CPU, description='Determines the task queue for this action'
    )
    summary_entry_threshold: int = Field(
        default=200,
        description=(
            'Maximum total number of entries across all reprocessed uploads for '
            'which a full per-entry JSON summary is written. Above this count the '
            'summary keeps only aggregate statistics and a Kibana pointer, and the '
            'individual logs must be inspected in Kibana instead.'
        ),
    )
    kibana_base_url: str = Field(
        default='',
        description=(
            'Base URL of the Kibana instance used to inspect reprocessing logs at '
            'scale. When set, the summary embeds a ready-to-open Discover link; '
            'otherwise only the query string is emitted.'
        ),
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
