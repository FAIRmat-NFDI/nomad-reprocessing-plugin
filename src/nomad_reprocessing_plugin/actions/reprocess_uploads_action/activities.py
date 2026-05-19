import asyncio
import json

from nomad.processing.base import ProcessStatus
from nomad.processing.data import Upload
from nomad.utils.structlogging import get_logger
from temporalio import activity

from nomad_reprocessing_plugin.actions.reprocess_uploads_action.models import (
    BuildReprocessSummaryInput,
    ReprocessSingleUploadInput,
)

logger = get_logger(__name__)


@activity.defn
async def reprocess_upload(data: ReprocessSingleUploadInput) -> None:
    """Reprocess a single upload and poll until it is fully processed."""
    upload = Upload.get(data.upload_id)
    upload.process_upload()
    while True:
        await asyncio.sleep(5)
        upload = Upload.get(data.upload_id)
        processed_count = upload.processed_entries_count
        total_count = upload.total_entries_count
        failed_count = upload.failed_entries_count
        progress_log = (
            f'upload_id: {data.upload_id}, '
            f'{processed_count}/{total_count} entries processed, '
            f'{failed_count} failures.'
        )
        logger.info(progress_log)
        if upload.process_status in ProcessStatus.STATUSES_COMPLETED:
            return


@activity.defn
async def build_reprocess_summary(data: BuildReprocessSummaryInput) -> dict:
    """Build summary payload after all uploads have been reprocessed.

    Creates both a detailed summary (saved to file) and a compact summary (returned).
    The detailed summary includes entry metadata, log statistics, and full logs
    in chronological order.
    """
    detailed_summary: dict = {}
    compact_results: list[dict] = []

    for upload_id in data.upload_ids:
        upload = Upload.get(upload_id)
        successful_entries = (
            upload.processed_entries_count - upload.failed_entries_count
        )
        failed_entries = upload.failed_entries_count
        compact_results.append(
            {
                'upload_id': upload_id,
                'status': upload.process_status,
                'entry_status': f'{successful_entries} success, {failed_entries} failures',
            }
        )

        entries = [
            _build_entry_summary(upload, entry)
            for entry in upload.entries_sublist(0, upload.total_entries_count)
        ]

        # Calculate upload-level statistics from all entries
        total_errors = sum(entry['log_stats']['ERROR'] for entry in entries)
        total_warnings = sum(entry['log_stats']['WARNING'] for entry in entries)
        total_info = sum(entry['log_stats']['INFO'] for entry in entries)
        total_debug = sum(entry['log_stats']['DEBUG'] for entry in entries)
        total_critical = sum(entry['log_stats']['CRITICAL'] for entry in entries)

        detailed_summary[upload_id] = {
            'status': upload.process_status,
            'stats': {
                'total_entries': upload.total_entries_count,
                'successful': successful_entries,
                'failed': failed_entries,
                'total_errors': total_errors,
                'total_warnings': total_warnings,
                'total_info': total_info,
                'total_debug': total_debug,
                'total_critical': total_critical,
            },
            'entries': entries,
        }

    summary_upload = Upload.get(data.upload_id)
    summary_filename = f'reprocessing_summary_{data.workflow_id}.json'
    with summary_upload.staging_upload_files.raw_file(
        summary_filename, 'wt'
    ) as summary_file:
        json.dump(detailed_summary, summary_file, indent=2)

    return {'uploads': compact_results}


def _count_logs_by_level(logs: list) -> dict[str, int]:
    """Count logs by their level field.

    Args:
        logs: List of processing log dictionaries (or strings for simple logs)

    Returns:
        Dictionary with counts for each log level
    """
    counts = {'ERROR': 0, 'WARNING': 0, 'INFO': 0, 'DEBUG': 0, 'CRITICAL': 0}
    for log in logs:
        if isinstance(log, dict):
            level = log.get('level', 'INFO')  # Default to INFO if level missing
            if level in counts:
                counts[level] += 1
        else:
            # For non-dict logs (e.g., simple strings), count as INFO
            counts['INFO'] += 1
    return counts


def _build_entry_summary(upload: Upload, entry) -> dict:
    """Read processing logs from archive and build entry summary with metadata.

    Args:
        upload: The Upload object containing the entry
        entry: The Entry object to summarize

    Returns:
        Dictionary containing entry metadata, log statistics, and chronological logs
    """
    logs: list = []
    processing_errors: list[str] = []

    try:
        with upload.upload_files.read_archive(entry.entry_id) as archive:
            entry_archive = archive.get(entry.entry_id, {})
            if not entry_archive and isinstance(archive, dict):
                entry_archive = archive
            logs = entry_archive.get('processing_logs', []) or []

            # Extract processing_errors from metadata if present
            metadata = entry_archive.get('metadata', {})
            processing_errors = metadata.get('processing_errors', []) or []
    except Exception:
        logs = []
        processing_errors = []

    log_stats = _count_logs_by_level(logs)

    return {
        'entry_id': entry.entry_id,
        'mainfile': getattr(entry, 'mainfile', '') or '',
        'parser': getattr(entry, 'parser_name', '') or '',
        'status': getattr(entry, 'process_status', 'UNKNOWN'),
        'log_stats': log_stats,
        'processing_errors': processing_errors,
        'logs': logs,  # Keep in chronological order
    }
