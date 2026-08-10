import asyncio
import json
from urllib.parse import quote

from nomad.archive.storage import ArchiveError
from nomad.config import config
from nomad.processing.base import ProcessStatus
from nomad.processing.data import Entry, Upload
from nomad.utils.structlogging import get_logger
from temporalio import activity

from nomad_reprocessing_plugin.actions.reprocess_uploads_action.models import (
    BuildReprocessSummaryInput,
    ReprocessSingleUploadInput,
)

logger = get_logger(__name__)

# Entry point id, see pyproject.toml [project.entry-points.'nomad.plugin']. Used to
# read deployment-level summary configuration (threshold, Kibana URL) at runtime.
ACTION_ENTRY_POINT_ID = (
    'nomad_reprocessing_plugin.actions:reprocess_uploads_action_entry_point'
)

# Elasticsearch/Kibana index pattern that NOMAD's Logstash log shipping writes to.
KIBANA_LOG_INDEX = 'nomad-logs-*'

LOG_LEVELS = ('ERROR', 'WARNING', 'INFO', 'DEBUG', 'CRITICAL')


@activity.defn
async def reprocess_upload(data: ReprocessSingleUploadInput) -> None:
    """Reprocess a single upload and poll until it is fully processed."""
    upload = Upload.get(data.upload_id)
    upload.process_upload()
    while True:
        await asyncio.sleep(5)
        upload = Upload.get(data.upload_id)
        logger.info(
            'reprocessing progress: upload_id: %s, %s/%s entries processed, '
            '%s failures.',
            data.upload_id,
            upload.processed_entries_count,
            upload.total_entries_count,
            upload.failed_entries_count,
        )
        if upload.process_status in ProcessStatus.STATUSES_COMPLETED:
            return


@activity.defn
async def build_reprocess_summary(data: BuildReprocessSummaryInput) -> dict:
    """Build summary payload after all uploads have been reprocessed.

    Creates both a detailed summary (saved to file) and a compact summary (returned).
    Below ``summary_entry_threshold`` total entries the detailed summary holds full
    per-entry metadata and chronological logs. Above it, the per-entry logs would make
    the file unmanageable, so the summary keeps only aggregate statistics plus a Kibana
    pointer and the logs are inspected in Kibana instead.
    """
    threshold, kibana_base_url = _get_summary_config()

    uploads = [Upload.get(upload_id) for upload_id in data.upload_ids]
    total_entries = sum(upload.total_entries_count for upload in uploads)
    defer_to_kibana = total_entries > threshold

    detailed_summary: dict = {
        'mode': 'kibana' if defer_to_kibana else 'full',
        'total_entries': total_entries,
        'uploads': {},
    }
    compact_results: list[dict] = []

    for upload in uploads:
        successful_entries = (
            upload.processed_entries_count - upload.failed_entries_count
        )
        failed_entries = upload.failed_entries_count
        compact_results.append(
            {
                'upload_id': upload.upload_id,
                'status': upload.process_status,
                'entry_status': f'{successful_entries} success, {failed_entries} failures',
            }
        )

        if defer_to_kibana:
            detailed_summary['uploads'][upload.upload_id] = (
                _build_kibana_upload_summary(
                    upload,
                    successful_entries,
                    failed_entries,
                    data.workflow_id,
                    kibana_base_url,
                )
            )
        else:
            detailed_summary['uploads'][upload.upload_id] = _build_full_upload_summary(
                upload, successful_entries, failed_entries
            )

    summary_upload = Upload.get(data.upload_id)
    summary_filename = f'reprocessing_summary_{data.workflow_id}.json'
    with summary_upload.staging_upload_files.raw_file(
        summary_filename, 'wt'
    ) as summary_file:
        json.dump(detailed_summary, summary_file, indent=2)

    return {'uploads': compact_results}


def _get_summary_config() -> tuple[int, str]:
    """Read summary settings (entry threshold, Kibana base URL) from the entry point."""
    entry_point = config.get_plugin_entry_point(ACTION_ENTRY_POINT_ID)
    return entry_point.summary_entry_threshold, entry_point.kibana_base_url


def _read_entry_logs(upload: Upload, entry: Entry) -> tuple[list, list]:
    """Read processing logs and processing errors from an entry's archive.

    Returns empty lists when the archive is missing or unreadable (e.g. an entry that
    was dropped during reprocessing because its mainfile no longer matched a parser).
    """
    try:
        with upload.upload_files.read_archive(entry.entry_id) as archive:
            entry_archive = archive[entry.entry_id]
            logs = entry_archive.get('processing_logs', []) or []
            metadata = entry_archive.get('metadata', {})
            processing_errors = metadata.get('processing_errors', []) or []
    except (ArchiveError, KeyError, FileNotFoundError):
        logger.warning('could not read archive for entry %s', entry.entry_id)
        return [], []
    return list(logs), list(processing_errors)


def _count_logs_by_level(logs: list) -> dict[str, int]:
    """Count logs by their level field, defaulting non-dict logs to INFO."""
    counts = {level: 0 for level in LOG_LEVELS}
    for log in logs:
        level = log.get('level', 'INFO') if isinstance(log, dict) else 'INFO'
        if level in counts:
            counts[level] += 1
    return counts


def _extract_high_priority_logs(logs: list, entry_id: str) -> list[dict]:
    """Extract high-priority logs (CRITICAL, ERROR, WARNING, DEBUG) with their indices.

    The returned logs are sorted by severity (CRITICAL first, then ERROR, WARNING,
    DEBUG) and carry the array index into the entry's chronological ``logs`` for quick
    navigation.
    """
    level_priority = {'CRITICAL': 0, 'ERROR': 1, 'WARNING': 2, 'DEBUG': 3}
    high_priority_logs = [
        {
            'level': log['level'],
            'event': log.get('event', ''),
            'entry_id': entry_id,
            'index': idx,
            'timestamp': log.get('timestamp', ''),
        }
        for idx, log in enumerate(logs)
        if isinstance(log, dict) and log.get('level') in level_priority
    ]
    high_priority_logs.sort(key=lambda log: level_priority[log['level']])
    return high_priority_logs


def _build_entry_summary(upload: Upload, entry: Entry) -> dict:
    """Read processing logs from archive and build entry summary with metadata."""
    logs, processing_errors = _read_entry_logs(upload, entry)
    return {
        'entry_id': entry.entry_id,
        'mainfile': entry.mainfile or '',
        'parser': entry.parser_name or '',
        'status': entry.process_status,
        'log_stats': _count_logs_by_level(logs),
        'high_priority_logs': _extract_high_priority_logs(logs, entry.entry_id),
        'processing_errors': processing_errors,
        'logs': logs,  # Keep in chronological order
    }


def _upload_stats(
    upload: Upload,
    successful_entries: int,
    failed_entries: int,
    log_totals: dict[str, int],
) -> dict:
    """Assemble upload-level statistics from entry counts and aggregated log levels."""
    return {
        'total_entries': upload.total_entries_count,
        'successful': successful_entries,
        'failed': failed_entries,
        'total_errors': log_totals['ERROR'],
        'total_warnings': log_totals['WARNING'],
        'total_info': log_totals['INFO'],
        'total_debug': log_totals['DEBUG'],
        'total_critical': log_totals['CRITICAL'],
    }


def _build_full_upload_summary(
    upload: Upload, successful_entries: int, failed_entries: int
) -> dict:
    """Full per-entry summary for uploads below the entry threshold."""
    entries = [
        _build_entry_summary(upload, entry)
        for entry in upload.entries_sublist(0, upload.total_entries_count)
    ]
    log_totals = {
        level: sum(entry['log_stats'][level] for entry in entries)
        for level in LOG_LEVELS
    }
    return {
        'status': upload.process_status,
        'stats': _upload_stats(upload, successful_entries, failed_entries, log_totals),
        'entries': entries,
    }


def _build_kibana_upload_summary(
    upload: Upload,
    successful_entries: int,
    failed_entries: int,
    workflow_id: str,
    kibana_base_url: str,
) -> dict:
    """Aggregate-only summary for large uploads, deferring log inspection to Kibana.

    Log-level counts are aggregated from the archives, but the (potentially huge)
    per-entry log arrays are not retained; those are what make the JSON unmanageable
    at scale, so they are left for Kibana.
    """
    log_totals = {level: 0 for level in LOG_LEVELS}
    for entry in upload.entries_sublist(0, upload.total_entries_count):
        logs, _ = _read_entry_logs(upload, entry)
        for level, count in _count_logs_by_level(logs).items():
            log_totals[level] += count
    return {
        'status': upload.process_status,
        'stats': _upload_stats(upload, successful_entries, failed_entries, log_totals),
        'kibana': _build_kibana_pointer(upload.upload_id, workflow_id, kibana_base_url),
    }


def _build_kibana_pointer(
    upload_id: str, workflow_id: str, kibana_base_url: str
) -> dict:
    """Build a Kibana Discover pointer (index, KQL query, optional deep link)."""
    query = f'nomad.upload_id:"{upload_id}"'
    pointer = {
        'index': KIBANA_LOG_INDEX,
        'query': query,
        'workflow_id': workflow_id,
    }
    if kibana_base_url:
        rison = f"(query:(language:kuery,query:'{query}'))"
        pointer['url'] = (
            f'{kibana_base_url.rstrip("/")}/app/discover#/?_a={quote(rison, safe="")}'
        )
    return pointer
