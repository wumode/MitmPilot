import asyncio
import inspect
import threading
import traceback

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler

from app import schemas
from app.chain import ChainBase
from app.core.config import settings
from app.core.ctx import Context
from app.core.event import Event, eventmanager
from app.helper.message import MessageHelper
from app.log import logger
from app.schemas import (
    AddonService,
    AddonServiceRegistration,
    ConfigChangeEventData,
    ScheduledTask,
)
from app.schemas.types import ChainEventType, EventType
from app.utils.singleton import SingletonClass
from app.utils.timer import TimerUtils

lock = threading.Lock()


class SchedulerChain(ChainBase):
    pass


class Scheduler(metaclass=SingletonClass):
    """Scheduler Management."""

    def __init__(self):
        # Scheduler service
        self._scheduler: BackgroundScheduler | None = None
        # Exit event
        self._event = threading.Event()
        # Lock
        self._lock = threading.RLock()
        # Running status of each service
        self._jobs: dict[str, ScheduledTask] = {}
        # User authentication failure count
        self._auth_count = 0
        # User authentication failure message sent
        self._auth_message = False
        self.init()

    @eventmanager.register(EventType.ConfigChanged)
    def _handle_config_changed(self, event: Event):
        """Handle configuration change events.

        :param event: Event object
        """
        if not event:
            return
        event_data: ConfigChangeEventData = event.event_data
        if event_data.key not in ["DEV"]:
            return
        logger.info(
            f"Configuration item {event_data.key} changed, reinitializing scheduler service..."
        )
        self.init()

    def init(self):
        """Initialize scheduler service."""

        # Stop the scheduler service
        self.stop()

        # Do not start the scheduler service in debug mode
        if settings.DEV:
            return

        with lock:
            # Running status of each service
            self._jobs = {
                "clear_cache": ScheduledTask(
                    name="Clear Cache", func=self.clear_cache, running=False
                ),
                "scheduler_job": ScheduledTask(
                    name="Common Scheduler Service",
                    func=SchedulerChain().scheduler_job,
                    running=False,
                ),
                "addon_market_refresh": ScheduledTask(
                    name="Addon Market Cache",
                    func=Context.addonmanager.async_get_online_addons,
                    running=False,
                    kwargs={"force": True},
                ),
            }

            # Create scheduler service
            self._scheduler = BackgroundScheduler(
                timezone=settings.TZ,
                executors={"default": ThreadPoolExecutor(settings.CONF.scheduler)},
            )

            # Common scheduler service
            self._scheduler.add_job(
                self.start,
                "interval",
                id="scheduler_job",
                name="Common Scheduler Service",
                minutes=10,
                kwargs={"job_id": "scheduler_job"},
            )

            # Cache clearing service, every 24 hours
            self._scheduler.add_job(
                self.start,
                "interval",
                id="clear_cache",
                name="Clear Cache",
                hours=settings.CONF.cache_lifespan / 3600,
                kwargs={"job_id": "clear_cache"},
            )

            # Addon market cache
            self._scheduler.add_job(
                self.start,
                "interval",
                id="addon_market_refresh",
                name="Addon Market Cache",
                minutes=30,
                kwargs={"job_id": "addon_market_refresh"},
            )

            # Start the scheduler service
            self._scheduler.start()

    def __prepare_job(self, job_id: str) -> ScheduledTask | None:
        """Prepare job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job.running:
                logger.warning(f"Job {job_id} - {job.name} is already running...")
                return None
            self._jobs[job_id].running = True
        return job

    def __finish_job(self, job_id: str):
        """Finish job."""
        with self._lock:
            try:
                self._jobs[job_id].running = False
            except KeyError:
                pass

    def start(self, job_id: str, *args, **kwargs):
        """Start job."""

        def __start_coro(coro):
            """Start coroutine."""
            return asyncio.run_coroutine_threadsafe(coro, Context.loop)

        # Get job
        job = self.__prepare_job(job_id)
        if not job:
            return
        # Start running
        try:
            if not kwargs:
                kwargs = job.kwargs
            func = job.func
            if not func:
                return
            if inspect.iscoroutinefunction(func):
                # Coroutine function
                __start_coro(func(*args, **kwargs))
            else:
                # Normal function
                job.func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Job {job.name} failed: {str(e)} - {traceback.format_exc()}")
            MessageHelper().put(
                title=f"{job.name} execution failed", message=str(e), role="system"
            )
            eventmanager.send_event(
                EventType.SystemError,
                {
                    "type": "scheduler",
                    "scheduler_id": job_id,
                    "scheduler_name": job.name,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                },
            )
        # Finished
        self.__finish_job(job_id)

    def remove_plugin_task(self, pid: str, task_id: str | None = None):
        """Remove jobs, can be a single job (including default job) or all jobs of an
        addon.

        :param pid: The addon ID
        :param task_id: Optional, specify the job_id of a single job to remove. If not
            provided, all jobs of the addon will be removed.
        """
        if not self._scheduler:
            return
        with self._lock:
            if task_id:
                # Remove single job
                service = self._jobs.pop(task_id, None)
                if not service:
                    return
                jobs_to_remove = [(task_id, service)]
            else:
                # Remove all jobs of the plugin
                jobs_to_remove = [
                    (job_id, service)
                    for job_id, service in self._jobs.items()
                    if service.pid == pid
                ]
                for task_id, _ in jobs_to_remove:
                    self._jobs.pop(task_id, None)
            if not jobs_to_remove:
                return
            plugin_name = Context.addonmanager.get_plugin_attr(pid, "addon_name")
            # Iterate and remove jobs
            for task_id, service in jobs_to_remove:
                try:
                    # Find and remove the corresponding job in the scheduler
                    job_removed = False
                    for job in list(self._scheduler.get_jobs()):
                        job_id_from_service = job.id.split("|")[0]
                        if task_id == job_id_from_service:
                            try:
                                self._scheduler.remove_job(job.id)
                                job_removed = True
                            except JobLookupError:
                                pass
                    if job_removed:
                        logger.info(
                            f"Removing addon task ({plugin_name}): {service.name}"
                        )  # noqa
                except Exception as e:
                    logger.error(
                        f"Failed to remove addon task: {str(e)} - {task_id}: {service}"
                    )
                    SchedulerChain().messagehelper.put(
                        title=f"Addon {plugin_name} job removal failed",
                        message=str(e),
                        role="system",
                    )

    def update_plugin_tasks(self, pid: str, name: str, services: list[AddonService]):
        """Update all tasks for an addon."""
        if not self._scheduler or not pid:
            return
        # Remove all jobs of this plugin
        self.remove_plugin_task(pid)
        # Get plugin services list
        with self._lock:
            # Get plugin name
            # Start registering plugin jobs
            for service in services:
                try:
                    sid = f"{pid}_{service.id}"
                    job_id = sid.split("|")[0]
                    self._jobs[job_id] = ScheduledTask(
                        name=service.name,
                        func=service.func,
                        pid=pid,
                        provider_name=name,
                        kwargs=service.func_kwargs,
                    )
                    self._scheduler.add_job(
                        self.start,
                        service.trigger,
                        id=sid,
                        name=service.name,
                        **service.kwargs,
                        kwargs={"job_id": job_id},
                        replace_existing=True,
                    )
                    logger.info(
                        f"Registering plugin job {name}: {service.name} - {service.trigger}"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to register plugin job {name}: {str(e)} - {service}"
                    )
                    SchedulerChain().messagehelper.put(
                        title=f"Addon {name} job registration failed",
                        message=str(e),
                        role="system",
                    )

    @eventmanager.register(ChainEventType.AddonServiceRegister)
    def _handle_addon_service_registration(self, event: Event):
        data: AddonServiceRegistration = event.event_data
        name = data.addon_name or data.addon_id
        self.update_plugin_tasks(pid=data.addon_id, name=name, services=data.services)

    @eventmanager.register(ChainEventType.AddonServiceDeregister)
    def _handle_addon_service_deregistration(self, event: Event):
        data: AddonServiceRegistration = event.event_data
        self.remove_plugin_task(data.addon_id)

    def list_tasks(self) -> list[schemas.ScheduleInfo]:
        """List all current jobs."""
        if not self._scheduler:
            return []
        with self._lock:
            # Return scheduled jobs
            schedulers = []
            # Deduplicate
            added = []
            # Avoid deadlock caused by _scheduler.shutdown() being blocked
            if not self._scheduler or not self._scheduler.running:
                return []
            jobs = self._scheduler.get_jobs()
            # Sort by next run time
            jobs.sort(key=lambda x: x.next_run_time)
            # Extract running jobs (to ensure one-time jobs are displayed correctly)
            for job_id, service in self._jobs.items():
                name = service.name
                provider_name = service.provider_name
                if service.running and name and provider_name:
                    if job_id not in added:
                        added.append(job_id)
                    schedulers.append(
                        schemas.ScheduleInfo(
                            id=job_id,
                            name=name,
                            provider=provider_name,
                            status="Running",
                        )
                    )
            # Get other pending jobs
            for job in jobs:
                job_id = job.id.split("|")[0]
                if job_id not in added:
                    added.append(job_id)
                else:
                    continue
                service = self._jobs.get(job_id)
                if not service:
                    continue
                # Job status
                status = "Running" if service.running else "Waiting"
                # Next run time
                next_run = TimerUtils.time_difference(job.next_run_time)
                schedulers.append(
                    schemas.ScheduleInfo(
                        id=job_id,
                        name=job.name,
                        provider=service.provider_name or "[System]",
                        status=status,
                        next_run=next_run,
                    )
                )
            return schedulers

    def stop(self):
        """Stop the scheduler service."""
        with lock:
            try:
                if self._scheduler:
                    logger.info("Stopping scheduler jobs...")
                    self._event.set()
                    self._scheduler.remove_all_jobs()
                    if self._scheduler.running:
                        self._scheduler.shutdown()
                    self._scheduler = None
                    logger.info("Scheduler jobs stopped.")
            except Exception as e:
                logger.error(
                    f"Failed to stop scheduler jobs: {str(e)} - {traceback.format_exc()}"
                )

    @staticmethod
    def clear_cache():
        """Clear cache."""
        SchedulerChain().clear_cache()
