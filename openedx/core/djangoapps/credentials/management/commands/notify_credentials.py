"""
A few places in the LMS want to notify the Credentials service when certain events
happen (like certificates being awarded or grades changing). To do this, they
listen for a signal. Sometimes we want to rebuild the data on these apps
regardless of an actual change in the database, either to recover from a bug or
to bootstrap a new feature we're rolling out for the first time.

This management command will manually trigger the receivers we care about.
(We don't want to trigger all receivers for these signals, since these are busy
signals.)
"""


import logging
import shlex
import sys

from datetime import datetime, timedelta
import dateutil.parser
from django.core.management.base import BaseCommand, CommandError
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from pytz import UTC

from openedx.core.djangoapps.credentials.models import NotifyCredentialsConfig
from openedx.core.djangoapps.credentials.tasks.v1.tasks import handle_notify_credentials

log = logging.getLogger(__name__)


def parsetime(timestr):
    dt = dateutil.parser.parse(timestr)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


class Command(BaseCommand):
    """
    Example usage:

    # Process all certs/grades changes for a given course:
    $ ./manage.py lms --settings=devstack_docker notify_credentials \
    --courses course-v1:edX+DemoX+Demo_Course

    # Process all certs/grades changes in a given time range:
    $ ./manage.py lms --settings=devstack_docker notify_credentials \
    --start-date 2018-06-01 --end-date 2018-07-31

    A Dry Run will produce output that looks like:

        DRY-RUN: This command would have handled changes for...
        3 Certificates:
            course-v1:edX+RecordsSelfPaced+1 for user records_one_cert
            course-v1:edX+RecordsSelfPaced+1 for user records
            course-v1:edX+RecordsSelfPaced+1 for user records_unverified
        3 Grades:
            course-v1:edX+RecordsSelfPaced+1 for user 14
            course-v1:edX+RecordsSelfPaced+1 for user 17
            course-v1:edX+RecordsSelfPaced+1 for user 18
    """
    help = (
        "Simulate certificate/grade changes without actually modifying database "
        "content. Specifically, trigger the handlers that send data to Credentials."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Just show a preview of what would happen.',
        )
        parser.add_argument(
            '--site',
            default=None,
            help="Site domain to notify for (if not specified, all sites are notified). Uses course_org_filter.",
        )
        parser.add_argument(
            '--courses',
            nargs='+',
            help='Send information only for specific courses.',
        )
        parser.add_argument(
            '--start-date',
            type=parsetime,
            help='Send information only for certificates or grades that have changed since this date.',
        )
        parser.add_argument(
            '--end-date',
            type=parsetime,
            help='Send information only for certificates or grades that have changed before this date.',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0,
            help="Number of seconds to sleep between processing queries, so that we don't flood our queues.",
        )
        parser.add_argument(
            '--page-size',
            type=int,
            default=100,
            help="Number of items to query at once.",
        )
        parser.add_argument(
            '--auto',
            action='store_true',
            help='Use to run the management command periodically',
        )
        parser.add_argument(
            '--args-from-database',
            action='store_true',
            help='Use arguments from the NotifyCredentialsConfig model instead of the command line.',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Run grade/cert change signal in verbose mode',
        )
        parser.add_argument(
            '--notify_programs',
            action='store_true',
            help='Send program award notifications with course notification tasks',
        )
        parser.add_argument(
            '--user_ids',
            default=None,
            nargs='+',
            help='Run the command for the given user or list of users',
        )

    def get_args_from_database(self):
        """ Returns an options dictionary from the current NotifyCredentialsConfig model. """
        config = NotifyCredentialsConfig.current()
        if not config.enabled:
            raise CommandError('NotifyCredentialsConfig is disabled, but --args-from-database was requested.')

        # This split will allow for quotes to wrap datetimes, like "2020-10-20 04:00:00" and other
        # arguments as if it were the command line
        argv = shlex.split(config.arguments)
        parser = self.create_parser('manage.py', 'notify_credentials')
        return parser.parse_args(argv).__dict__   # we want a dictionary, not a non-iterable Namespace object

    def handle(self, *args, **options):
        if options['args_from_database']:
            options = self.get_args_from_database()

        if options['auto']:
            options['end_date'] = datetime.now().replace(minute=0, second=0, microsecond=0)
            options['start_date'] = options['end_date'] - timedelta(hours=4)

        log.info(
            "notify_credentials starting, dry-run=%s, site=%s, delay=%d seconds, page_size=%d, "
            "from=%s, to=%s, notify_programs=%s, user_ids=%s, execution=%s",
            options['dry_run'],
            options['site'],
            options['delay'],
            options['page_size'],
            options['start_date'] if options['start_date'] else 'NA',
            options['end_date'] if options['end_date'] else 'NA',
            options['notify_programs'],
            options['user_ids'],
            'auto' if options['auto'] else 'manual',
        )

        course_keys = self.get_course_keys(options['courses'])
        if not (course_keys or options['start_date'] or options['end_date'] or options['user_ids']):
            raise CommandError('You must specify a filter (e.g. --courses= or --start-date or --user_ids)')

        handle_notify_credentials.delay(options, course_keys)

    def get_course_keys(self, courses=None):
        """
        Return a list of CourseKeys that we will emit signals to.

        `courses` is an optional list of strings that can be parsed into
        CourseKeys. If `courses` is empty or None, we will default to returning
        all courses in the modulestore (which can be very expensive). If one of
        the strings passed in the list for `courses` does not parse correctly,
        it is a fatal error and will cause us to exit the entire process.
        """
        # Use specific courses if specified, but fall back to all courses.
        if not courses:
            courses = []
        course_keys = []

        log.info("%d courses specified: %s", len(courses), ", ".join(courses))
        for course_id in courses:
            try:
                course_keys.append(CourseKey.from_string(course_id))
            except InvalidKeyError:
                log.fatal("%s is not a parseable CourseKey", course_id)
                sys.exit(1)

        return course_keys
