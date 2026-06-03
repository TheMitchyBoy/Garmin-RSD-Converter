"""Tests for background upload job retention behavior."""

from sonar_upload_server import MAX_RETAINED_JOBS, JobStatus, ProcessingJob, _prune_old_jobs


def test_prune_old_jobs_keeps_active_jobs():
    jobs = {
        'run': ProcessingJob(id='run', status=JobStatus.RUNNING, created_at=0.0),
    }
    for idx in range(MAX_RETAINED_JOBS + 5):
        jobs[f'c{idx}'] = ProcessingJob(
            id=f'c{idx}',
            status=JobStatus.COMPLETED,
            created_at=float(idx + 1),
        )

    _prune_old_jobs(jobs)

    assert 'run' in jobs
    assert len(jobs) == MAX_RETAINED_JOBS
    for removed in range(6):
        assert f'c{removed}' not in jobs
    assert f'c{MAX_RETAINED_JOBS + 4}' in jobs


def test_prune_old_jobs_does_not_evict_when_only_active_jobs():
    jobs = {}
    for idx in range(MAX_RETAINED_JOBS + 12):
        status = JobStatus.RUNNING if idx % 2 else JobStatus.PENDING
        jobs[f'a{idx}'] = ProcessingJob(id=f'a{idx}', status=status, created_at=float(idx))

    _prune_old_jobs(jobs)

    assert len(jobs) == MAX_RETAINED_JOBS + 12
