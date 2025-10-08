from app.scheduler import Scheduler


def init_scheduler():
    """
    Initializes the scheduler.
    """
    Scheduler()


def stop_scheduler():
    """
    Stops the scheduler.
    """
    Scheduler().stop()


def restart_scheduler():
    """
    Restarts the scheduler.
    """
    Scheduler().init()


def init_plugin_scheduler():
    """
    Initializes plugin schedulers.
    """
    Scheduler().init_plugin_jobs()
