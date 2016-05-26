# coding: UTF-8
"""
Tests for support views.
"""

from datetime import datetime, timedelta
import itertools
import json
import re

import ddt
from django.core.urlresolvers import reverse
import freezegun
from nose.plugins.attrib import attr
from pytz import UTC

from course_modes.models import CourseMode
from course_modes.tests.factories import CourseModeFactory
from lms.djangoapps.verify_student.models import VerificationDeadline
from student.models import CourseEnrollment, ManualEnrollmentAudit, ENROLLED_TO_ENROLLED
from student.roles import GlobalStaff, SupportStaffRole
from student.tests.factories import UserFactory, CourseEnrollmentFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase, SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory


class SupportViewTestCase(ModuleStoreTestCase):
    """
    Base class for support view tests.
    """

    USERNAME = "support"
    EMAIL = "support@example.com"
    PASSWORD = "support"

    def setUp(self):
        """Create a user and log in. """
        super(SupportViewTestCase, self).setUp()
        self.user = UserFactory(username=self.USERNAME, email=self.EMAIL, password=self.PASSWORD)
        self.course = CourseFactory.create()
        success = self.client.login(username=self.USERNAME, password=self.PASSWORD)
        self.assertTrue(success, msg="Could not log in")


@attr('shard_3')
@ddt.ddt
class SupportViewAccessTests(SupportViewTestCase):
    """
    Tests for access control of support views.
    """

    @ddt.data(*(
        (url_name, role, has_access)
        for (url_name, (role, has_access))
        in itertools.product((
            'support:index',
            'support:certificates',
            'support:refund',
            'support:enrollment',
            'support:enrollment_list'
        ), (
            (GlobalStaff, True),
            (SupportStaffRole, True),
            (None, False)
        ))
    ))
    @ddt.unpack
    def test_access(self, url_name, role, has_access):
        if role is not None:
            role().add_users(self.user)

        url = reverse(url_name)
        response = self.client.get(url)

        if has_access:
            self.assertEqual(response.status_code, 200)
        else:
            self.assertEqual(response.status_code, 403)

    @ddt.data(
        "support:index",
        "support:certificates",
        "support:refund",
        "support:enrollment",
        "support:enrollment_list"
    )
    def test_require_login(self, url_name):
        url = reverse(url_name)

        # Log out then try to retrieve the page
        self.client.logout()
        response = self.client.get(url)

        # Expect a redirect to the login page
        redirect_url = "{login_url}?next={original_url}".format(
            login_url=reverse("signin_user"),
            original_url=url,
        )
        self.assertRedirects(response, redirect_url)


class SupportViewIndexTests(SupportViewTestCase):
    """
    Tests for the support index view.
    """

    EXPECTED_URL_NAMES = [
        "support:certificates",
        "support:refund",
    ]

    def setUp(self):
        """Make the user support staff. """
        super(SupportViewIndexTests, self).setUp()
        SupportStaffRole().add_users(self.user)

    def test_index(self):
        response = self.client.get(reverse("support:index"))
        self.assertContains(response, "Support")

        # Check that all the expected links appear on the index page.
        for url_name in self.EXPECTED_URL_NAMES:
            self.assertContains(response, reverse(url_name))


class SupportViewCertificatesTests(SupportViewTestCase):
    """
    Tests for the certificates support view.
    """
    def setUp(self):
        """Make the user support staff. """
        super(SupportViewCertificatesTests, self).setUp()
        SupportStaffRole().add_users(self.user)

    def test_certificates_no_filter(self):
        # Check that an empty initial filter is passed to the JavaScript client correctly.
        response = self.client.get(reverse("support:certificates"))
        self.assertContains(response, "userFilter: ''")

    def test_certificates_with_user_filter(self):
        # Check that an initial filter is passed to the JavaScript client.
        url = reverse("support:certificates") + "?user=student@example.com"
        response = self.client.get(url)
        self.assertContains(response, "userFilter: 'student@example.com'")

    def test_certificates_along_with_course_filter(self):
        # Check that an initial filter is passed to the JavaScript client.
        url = reverse("support:certificates") + "?user=student@example.com&course_id=" + unicode(self.course.id)
        response = self.client.get(url)
        self.assertContains(response, "userFilter: 'student@example.com'")
        self.assertContains(response, "courseFilter: '" + unicode(self.course.id) + "'")


@ddt.ddt
class SupportViewEnrollmentsTests(SharedModuleStoreTestCase, SupportViewTestCase):
    """Tests for the enrollment support view."""

    def setUp(self):
        super(SupportViewEnrollmentsTests, self).setUp()
        SupportStaffRole().add_users(self.user)

        self.course = CourseFactory(display_name=u'teꜱᴛ')
        self.student = UserFactory.create(username='student', email='test@example.com', password='test')

        for mode in (
                CourseMode.AUDIT, CourseMode.PROFESSIONAL, CourseMode.NO_ID_PROFESSIONAL_MODE
        ):
            CourseModeFactory.create(mode_slug=mode, course_id=self.course.id)  # pylint: disable=no-member
        self.verified_mode = CourseModeFactory.create(mode_slug=CourseMode.VERIFIED, course_id=self.course.id)  # pylint: disable=no-member

        self.verification_deadline = VerificationDeadline(
            course_key=self.course.id,  # pylint: disable=no-member
            deadline=datetime.now(UTC) + timedelta(days=365)
        )
        self.verification_deadline.save()

        CourseEnrollmentFactory.create(mode=CourseMode.AUDIT, user=self.student, course_id=self.course.id)  # pylint: disable=no-member

        self.url = reverse('support:enrollment_list', kwargs={'username_or_email': self.student.username})

    def assert_enrollment(self, mode):
        """
        Assert that the student's enrollment has the correct mode.
        """
        enrollment = CourseEnrollment.get_enrollment(self.student, self.course.id)  # pylint: disable=no-member
        self.assertEqual(enrollment.mode, mode)

    @ddt.data('username', 'email')
    def test_get_enrollments(self, search_string_type):
        url = reverse(
            'support:enrollment_list',
            kwargs={'username_or_email': getattr(self.student, search_string_type)}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(len(data), 1)
        self.assertDictContainsSubset({
            'mode': CourseMode.AUDIT,
            'manual_enrollment': {},
            'user': self.student.username,
            'course_id': unicode(self.course.id),  # pylint: disable=no-member
            'is_active': True,
            'verified_upgrade_deadline': None,
        }, data[0])
        self.assertEqual(
            {CourseMode.VERIFIED, CourseMode.AUDIT, CourseMode.NO_ID_PROFESSIONAL_MODE, CourseMode.PROFESSIONAL},
            {mode['slug'] for mode in data[0]['course_modes']}
        )

    def test_get_manual_enrollment_history(self):
        ManualEnrollmentAudit.create_manual_enrollment_audit(
            self.user,
            self.student.email,
            ENROLLED_TO_ENROLLED,
            'Financial Assistance',
            CourseEnrollment.objects.get(course_id=self.course.id, user=self.student)  # pylint: disable=no-member
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertDictContainsSubset({
            'enrolled_by': self.user.email,
            'reason': 'Financial Assistance',
        }, json.loads(response.content)[0]['manual_enrollment'])

    @ddt.data('username', 'email')
    def test_change_enrollment(self, search_string_type):
        self.assertIsNone(ManualEnrollmentAudit.get_manual_enrollment_by_email(self.student.email))
        url = reverse(
            'support:enrollment_list',
            kwargs={'username_or_email': getattr(self.student, search_string_type)}
        )
        response = self.client.post(url, data={
            'course_id': unicode(self.course.id),  # pylint: disable=no-member
            'old_mode': CourseMode.AUDIT,
            'new_mode': CourseMode.VERIFIED,
            'reason': 'Financial Assistance'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(ManualEnrollmentAudit.get_manual_enrollment_by_email(self.student.email))
        self.assert_enrollment(CourseMode.VERIFIED)

    @ddt.data(
        ({}, r"The field '\w+' is required."),
        ({'course_id': 'bad course key'}, 'Could not parse course key.'),
        ({
            'course_id': 'course-v1:TestX+T101+2015',
            'old_mode': CourseMode.AUDIT,
            'new_mode': CourseMode.VERIFIED,
            'reason': ''
        }, 'Could not find enrollment for user'),
        ({
            'course_id': None,
            'old_mode': CourseMode.HONOR,
            'new_mode': CourseMode.VERIFIED,
            'reason': ''
        }, r'User \w+ is not enrolled with mode ' + CourseMode.HONOR),
        ({
            'course_id': None,
            'old_mode': CourseMode.AUDIT,
            'new_mode': CourseMode.CREDIT_MODE,
            'reason': ''
        }, "Specified course mode '{}' unavailable".format(CourseMode.CREDIT_MODE))
    )
    @ddt.unpack
    def test_change_enrollment_bad_data(self, data, error_message):
        # `self` isn't available from within the DDT declaration, so
        # assign the course ID here
        if 'course_id' in data and data['course_id'] is None:
            data['course_id'] = unicode(self.course.id)  # pylint: disable=no-member
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(re.match(error_message, response.content))
        self.assert_enrollment(CourseMode.AUDIT)
        self.assertIsNone(ManualEnrollmentAudit.get_manual_enrollment_by_email(self.student.email))

    @freezegun.freeze_time('2016-01-02 12:00:00')
    @ddt.data('username', 'email')
    def test_get_enrollments_with_expired_mode(self, search_string_type):
        """ Verify that verified mode with expired date will appear on support page. """
        self.verified_mode.expiration_datetime = datetime.now(UTC) + timedelta(days=-1)
        self.verified_mode.save()

        url = reverse(
            'support:enrollment_list',
            kwargs={'username_or_email': getattr(self.student, search_string_type)}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(len(data), 1)

        self.assertEqual(
            self._generate_modes_data(),
            data[0]['course_modes']
        )

        self.assertEqual(
            {CourseMode.VERIFIED, CourseMode.AUDIT, CourseMode.NO_ID_PROFESSIONAL_MODE, CourseMode.PROFESSIONAL},
            {mode['slug'] for mode in data[0]['course_modes']}
        )

    def _generate_modes_data(self):
        """ Generate course modes dict """

        modes = CourseMode.modes_for_course(
            self.course.id,
            include_expired=True
        )
        modes_data = []
        for mode in modes:
            expiry = mode.expiration_datetime.strftime('%Y-%m-%dT%H:%M:%SZ') if mode.expiration_datetime else None
            modes_data.append({
                'sku': mode.sku,
                'expiration_datetime': expiry,
                'name': mode.name,
                'currency': mode.currency,
                'bulk_sku': mode.bulk_sku,
                'min_price': mode.min_price,
                'suggested_prices': mode.suggested_prices,
                'slug': mode.slug,
                'description': mode.description
            })

        return modes_data

    @ddt.data('username', 'email')
    def test_change_enrollment_to_expired_verified(self, search_string_type):
        """ Verify that support staff can change the student enrollment
        to expired verified mode.
        """
        self.verified_mode.expiration_datetime = datetime.now(UTC) + timedelta(days=-100)
        self.verified_mode.save()

        self.assertIsNone(ManualEnrollmentAudit.get_manual_enrollment_by_email(self.student.email))
        url = reverse(
            'support:enrollment_list',
            kwargs={'username_or_email': getattr(self.student, search_string_type)}
        )
        response = self.client.post(url, data={
            'course_id': unicode(self.course.id),  # pylint: disable=no-member
            'old_mode': CourseMode.AUDIT,
            'new_mode': CourseMode.VERIFIED,
            'reason': 'Financial Assistance'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(ManualEnrollmentAudit.get_manual_enrollment_by_email(self.student.email))
        self.assert_enrollment(CourseMode.VERIFIED)
