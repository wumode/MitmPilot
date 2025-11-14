import datetime
import random


class TimerUtils:
    @staticmethod
    def random_scheduler(
        num_executions: int = 1,
        begin_hour: int = 7,
        end_hour: int = 23,
        min_interval: int = 20,
        max_interval: int = 40,
    ) -> list[datetime.datetime]:
        """Generates random timers based on the number of executions.

        :param num_executions: Number of executions
        :param begin_hour: Start hour
        :param end_hour: End hour
        :param min_interval: Minimum interval in minutes
        :param max_interval: Maximum interval in minutes
        """
        trigger: list = []
        # Current time
        now = datetime.datetime.now()
        # Create a random time trigger
        random_trigger = now.replace(hour=begin_hour, minute=0, second=0, microsecond=0)
        for _ in range(num_executions):
            # Randomly generate the time interval for the next task
            interval_minutes = random.randint(min_interval, max_interval)
            random_interval = datetime.timedelta(minutes=interval_minutes)
            # Record the time trigger of the previous task
            last_random_trigger = random_trigger
            # Update the current time to the time trigger of the next task
            random_trigger += random_interval
            # Exit when the end time is reached or time goes backward
            if (
                random_trigger.hour > end_hour
                or random_trigger.hour < last_random_trigger.hour
            ):
                break
            # Add to queue
            trigger.append(random_trigger)

        return trigger

    @staticmethod
    def random_even_scheduler(
        num_executions: int = 1, begin_hour: int = 7, end_hour: int = 23
    ) -> list[datetime.datetime]:
        """Generates random timers as evenly as possible based on the number of
        executions.

        :param num_executions: Number of executions
        :param begin_hour: Start hour of the planned range
        :param end_hour: End hour of the planned range.
        """
        trigger_times = []
        start_time = datetime.datetime.now().replace(
            hour=begin_hour, minute=0, second=0, microsecond=0
        )
        end_time = datetime.datetime.now().replace(
            hour=end_hour, minute=0, second=0, microsecond=0
        )

        # Calculate total minutes within the range
        total_minutes = int((end_time - start_time).total_seconds() / 60)
        # Calculate the average length of each execution time segment
        segment_length = total_minutes // num_executions

        for i in range(num_executions):
            # Randomly select a point within each segment
            start_segment = segment_length * i
            end_segment = start_segment + segment_length
            minute = random.randint(start_segment, end_segment - 1)
            trigger_time = start_time + datetime.timedelta(minutes=minute)
            trigger_times.append(trigger_time)

        return trigger_times

    @staticmethod
    def time_difference(input_datetime: datetime.datetime) -> str:
        """Calculates the time difference between the input time and the current time.

        :return:
            - The time difference if the input time is greater than the current time
            - "", otherwise
        """
        if not input_datetime:
            return ""
        current_datetime = datetime.datetime.now(datetime.UTC).astimezone()
        time_difference = input_datetime - current_datetime

        if time_difference.total_seconds() < 0:
            return ""

        days = time_difference.days
        hours, remainder = divmod(time_difference.seconds, 3600)
        minutes, second = divmod(remainder, 60)

        time_difference_string = ""
        if days > 0:
            time_difference_string += f"{days}天"
        if hours > 0:
            time_difference_string += f"{hours}小时"
        if minutes > 0:
            time_difference_string += f"{minutes}分钟"
        if not time_difference_string and second:
            time_difference_string = f"{second}秒"

        return time_difference_string

    @staticmethod
    def diff_minutes(input_datetime: datetime.datetime) -> int:
        """Calculates the minute difference between the current time and the input
        time."""
        if not input_datetime:
            return 0
        time_difference = datetime.datetime.now() - input_datetime
        return int(time_difference.total_seconds() / 60)
